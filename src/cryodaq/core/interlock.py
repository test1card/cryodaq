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
import hashlib
import json
import logging
import math
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from cryodaq.core.atomic_write import atomic_write_text
from cryodaq.core.broker import DataBroker, PublishedReading
from cryodaq.core.descriptor_transport import encode_descriptor_envelope
from cryodaq.core.physical_policy import PhysicalPolicyReceipt, receipt_for_applied_policy
from cryodaq.core.shutdown_settlement import await_executor_owner, cancel_and_settle_tasks
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
_MAX_PENDING_OPERATOR_TRANSITIONS = 1024
_MAX_OPERATOR_TRANSITION_RECEIPTS = 1024
_MAX_OPERATOR_STATE_BYTES = 4 * 1024 * 1024
_OPERATOR_TRANSITION_RECEIPT_KEYS = frozenset(
    {
        "enabled",
        "previous_enabled",
        "operator",
        "changed_at",
        "request_id",
        "notice",
        "experiment_id",
        "policy_fingerprint",
        "commit_receipt",
    }
)
_LEGACY_OPERATOR_TRANSITION_RECEIPT_KEYS = frozenset(
    {"enabled", "operator", "changed_at", "request_id", "notice", "commit_receipt"}
)
_OPERATOR_LOG_COMMIT_RECEIPT_KEYS = frozenset({"schema", "request_id", "entry_id", "experiment_id", "committed"})

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


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        type(value) is str
        and len(value) == length
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _interlock_policy_fingerprint(condition: InterlockCondition) -> str:
    bindings = [
        {
            "instrument_id": binding.instrument_id,
            "source_key": binding.source_key,
            "channel_id": binding.channel_id,
            "descriptor_sha256": hashlib.sha256(binding.descriptor_envelope).hexdigest(),
        }
        for binding in sorted(
            condition.channel_bindings,
            key=lambda item: (item.instrument_id, item.source_key, item.channel_id, item.descriptor_envelope),
        )
    ]
    policy = {
        "name": condition.name,
        "description": condition.description,
        "channel_ids": sorted(condition.channel_ids),
        "channel_bindings": bindings,
        "threshold": condition.threshold,
        "comparison": condition.comparison,
        "action": condition.action,
        "cooldown_s": condition.cooldown_s,
        "operator_disableable": condition.operator_disableable,
        "enabled_by_default": condition.enabled_by_default,
    }
    canonical = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validated_operator_transition_receipt(receipt: object) -> dict[str, Any]:
    if type(receipt) is not dict or frozenset(receipt) not in {
        _OPERATOR_TRANSITION_RECEIPT_KEYS,
        _LEGACY_OPERATOR_TRANSITION_RECEIPT_KEYS,
    }:
        raise ValueError("operator transition receipt keys are invalid")
    enabled = receipt.get("enabled")
    previous_enabled = receipt.get("previous_enabled")
    operator = receipt.get("operator")
    changed_at = receipt.get("changed_at")
    request_id = receipt.get("request_id")
    notice = receipt.get("notice")
    commit_receipt = receipt.get("commit_receipt")
    if (
        type(enabled) is not bool
        or (frozenset(receipt) == _OPERATOR_TRANSITION_RECEIPT_KEYS and type(previous_enabled) is not bool)
        or type(operator) is not str
        or not operator.strip()
        or len(operator.encode("utf-8")) > 512
        or type(notice) is not str
        or not notice
        or len(notice.encode("utf-8")) > 4096
        or not _is_lower_hex(request_id, 32)
        or type(changed_at) is not str
    ):
        raise ValueError("operator transition receipt fields are invalid")
    try:
        parsed_at = datetime.fromisoformat(changed_at)
    except ValueError as exc:
        raise ValueError("operator transition timestamp is invalid") from exc
    if parsed_at.tzinfo is None or parsed_at.utcoffset() is None:
        raise ValueError("operator transition timestamp is invalid")
    if type(commit_receipt) is not dict or frozenset(commit_receipt) != _OPERATOR_LOG_COMMIT_RECEIPT_KEYS:
        raise ValueError("operator transition commit receipt is invalid")
    experiment_id = commit_receipt.get("experiment_id")
    if (
        commit_receipt.get("schema") != "operator_log_commit_v1"
        or commit_receipt.get("request_id") != request_id
        or type(commit_receipt.get("entry_id")) is not int
        or commit_receipt["entry_id"] <= 0
        or (experiment_id is not None and (type(experiment_id) is not str or not experiment_id))
        or commit_receipt.get("committed") is not True
    ):
        raise ValueError("operator transition commit receipt is invalid")
    if frozenset(receipt) == _OPERATOR_TRANSITION_RECEIPT_KEYS:
        if receipt.get("experiment_id") != experiment_id or not _is_lower_hex(receipt.get("policy_fingerprint"), 64):
            raise ValueError("operator transition authority binding is invalid")
    detached = dict(receipt)
    detached["commit_receipt"] = dict(commit_receipt)
    return detached


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
    operator_disableable: bool = True
    enabled_by_default: bool = True

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
        if type(self.operator_disableable) is not bool:
            raise ValueError(f"Блокировка '{self.name}': operator_disableable must be an exact bool")
        if type(self.enabled_by_default) is not bool:
            raise ValueError(f"Блокировка '{self.name}': enabled_by_default must be an exact bool")

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
    enabled: bool = True
    latest_readings: dict[str, Reading] = field(default_factory=dict)
    condition_active: bool = False
    last_suppressed_warning: datetime | None = None
    disable_receipt: dict[str, Any] | None = None
    last_transition_receipt: dict[str, Any] | None = None
    pending_transition_receipts: list[dict[str, Any]] = field(default_factory=list)
    transition_receipts: list[dict[str, Any]] = field(default_factory=list)


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
        suppressed_handler: Callable[[InterlockCondition, Reading, str], Any] | None = None,
        state_changed_handler: Callable[[], Any] | None = None,
        state_path: Path | None = None,
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
        self._suppressed_handler = suppressed_handler
        self._state_changed_handler = state_changed_handler
        self._state_path = state_path
        self._state_change_lock = asyncio.Lock()
        self._retired_operator_state: dict[str, dict[str, Any]] = {}
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
            raw: dict[str, Any] = yaml.safe_load(snapshot)
        except yaml.YAMLError as exc:
            raise InterlockConfigError(f"interlocks.yaml at {config_path}: YAML parse error — {exc}") from exc

        if not isinstance(raw, dict):
            raise InterlockConfigError(f"interlocks.yaml at {config_path}: expected mapping, got {type(raw).__name__}")

        entries = raw.get("interlocks", [])
        if not isinstance(entries, list):
            raise InterlockConfigError(
                f"interlocks.yaml at {config_path}: 'interlocks' must be a list, got {type(entries).__name__}"
            )

        operator_disableable_default = raw.get("operator_disableable", False)
        enabled_by_default = raw.get("enabled_by_default", True)
        if type(operator_disableable_default) is not bool or type(enabled_by_default) is not bool:
            raise InterlockConfigError(
                f"interlocks.yaml at {config_path}: operator_disableable and enabled_by_default must be exact bools"
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
                    operator_disableable=operator_disableable_default,
                    enabled_by_default=enabled_by_default,
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
        self._interlocks[condition.name] = _InterlockRecord(
            condition=condition,
            enabled=condition.enabled_by_default,
        )
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
        identity_matching = [
            record
            for record in self._interlocks.values()
            if record.condition.matches_reading(reading, descriptor_envelope)
        ]
        matching = [record for record in identity_matching if record.enabled and record.state == InterlockState.ARMED]
        protected_matching = [record for record in identity_matching if record.enabled]

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
            elif identity_matching:
                self._nonusable_windows.pop(reading.channel, None)
        elif protected_matching:
            if math.isinf(reading.value) and any(
                record.condition.is_triggered(reading.value) for record in identity_matching
            ):
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
        elif identity_matching:
            self._nonusable_windows.pop(reading.channel, None)
            if not (
                math.isinf(reading.value)
                and any(record.condition.is_triggered(reading.value) for record in identity_matching)
            ):
                return

        for record in identity_matching:
            if reading.is_usable() or math.isinf(reading.value):
                record.latest_readings[reading.channel] = reading

        for record in identity_matching:
            if record.enabled:
                continue
            triggered = (reading.is_usable() or math.isinf(reading.value)) and record.condition.is_triggered(
                reading.value
            )
            if not triggered:
                record.condition_active = any(
                    (latest.is_usable() or math.isinf(latest.value)) and record.condition.is_triggered(latest.value)
                    for latest in record.latest_readings.values()
                )
                continue
            now = datetime.now(UTC)
            repeat_s = record.condition.cooldown_s if record.condition.cooldown_s > 0 else 60.0
            should_warn = (
                not record.condition_active
                or record.last_suppressed_warning is None
                or (now - record.last_suppressed_warning).total_seconds() >= repeat_s
            )
            record.condition_active = True
            if should_warn:
                await self._warn_suppressed(record, reading, now=now)

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

    async def _warn_suppressed(
        self,
        record: _InterlockRecord,
        reading: Reading,
        *,
        now: datetime,
    ) -> None:
        """Publish one loud observation while deliberately suppressing action."""
        condition = record.condition
        message = (
            f"Блокировка '{condition.name}' подавлена решением оператора: "
            f"значение {reading.value:.4g} {reading.unit} пересекло порог "
            f"{condition.comparison} {condition.threshold:.4g}; "
            f"действие '{condition.action}' не выполнено."
        )
        self._events.append(
            InterlockEvent(
                timestamp=now,
                interlock_name=condition.name,
                channel=reading.channel,
                value=reading.value,
                threshold=condition.threshold,
                action_taken=f"suppressed:{condition.action}",
            )
        )
        logger.warning(message)
        if self._suppressed_handler is not None:
            try:
                result = self._suppressed_handler(condition, reading, message)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error(
                    "Suppressed interlock warning publication failed for '%s': %s",
                    condition.name,
                    type(exc).__name__,
                )
                return
        record.last_suppressed_warning = now

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

    @staticmethod
    def operator_notice(condition: InterlockCondition, *, enabled: bool) -> str:
        """Return the exact warning text receipted before an operator toggle."""
        if enabled:
            return (
                f"Блокировка '{condition.name}' снова активна. Если последнее показание уже пересекло порог "
                f"{condition.comparison} {condition.threshold:.4g}, действие '{condition.action}' "
                "будет выполнено немедленно."
            )
        return (
            f"Блокировка '{condition.name}' продолжит оценивать условие "
            f"{condition.comparison} {condition.threshold:.4g}, но действие '{condition.action}' "
            "будет подавлено решением оператора; при нарушении будет выдано предупреждение."
        )

    def get_operator_state(self) -> list[dict[str, Any]]:
        """Return detached per-row operator state for commands and presentation."""
        return [
            {
                "name": name,
                "enabled": record.enabled,
                "operator_disableable": record.condition.operator_disableable,
                "action": record.condition.action,
                "comparison": record.condition.comparison,
                "threshold": record.condition.threshold,
                "disable_receipt": None if record.disable_receipt is None else dict(record.disable_receipt),
                "last_transition_receipt": (
                    None if record.last_transition_receipt is None else dict(record.last_transition_receipt)
                ),
                "pending_transition_receipts": [dict(receipt) for receipt in record.pending_transition_receipts],
                "transition_receipts": [dict(receipt) for receipt in record.transition_receipts],
            }
            for name, record in self._interlocks.items()
        ]

    def prepare_operator_toggle(self, interlock_name: str, *, enabled: bool) -> str:
        """Validate one toggle target and return the exact text to receipt."""
        if type(enabled) is not bool:
            raise TypeError("enabled must be an exact bool")
        record = self._interlocks.get(interlock_name)
        if record is None:
            raise KeyError(interlock_name)
        if not record.condition.operator_disableable:
            raise PermissionError(interlock_name)
        if len(record.pending_transition_receipts) >= _MAX_PENDING_OPERATOR_TRANSITIONS:
            raise RuntimeError("interlock operator provenance backlog is full")
        return self.operator_notice(record.condition, enabled=enabled)

    def disabled_interlocks(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, record in self._interlocks.items() if not record.enabled))

    def operator_transition_pending(self, interlock_name: str, request_id: str) -> bool:
        """Return whether exact experiment provenance still needs settlement."""
        record = self._interlocks.get(interlock_name)
        if record is None:
            raise KeyError(interlock_name)
        return any(receipt.get("request_id") == request_id for receipt in record.pending_transition_receipts)

    def _persistent_operator_states(
        self,
        *,
        target_name: str | None = None,
        target_enabled: bool | None = None,
        target_receipt: dict[str, Any] | None = None,
        target_pending: list[dict[str, Any]] | None = None,
        target_transitions: list[dict[str, Any]] | None = None,
        clear_pending: bool = False,
    ) -> dict[str, dict[str, Any]]:
        states = {name: dict(state) for name, state in self._retired_operator_state.items()}
        for name, item in self._interlocks.items():
            receipt = target_receipt if name == target_name else item.last_transition_receipt
            if receipt is None:
                continue
            if name == target_name:
                if target_enabled is None or target_pending is None or target_transitions is None:
                    raise RuntimeError("target operator state is incomplete")
                enabled = target_enabled
                pending = target_pending
                transitions = target_transitions
            else:
                enabled = item.enabled
                pending = [] if clear_pending else item.pending_transition_receipts
                transitions = item.transition_receipts
            states[name] = {
                "enabled": enabled,
                "receipt": dict(receipt),
                "pending_receipts": [dict(pending_receipt) for pending_receipt in pending],
                "transition_receipts": [dict(transition_receipt) for transition_receipt in transitions],
            }
        return states

    async def set_enabled(
        self,
        interlock_name: str,
        *,
        enabled: bool,
        operator: str,
        changed_at: datetime,
        request_id: str,
        notice: str,
        commit_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist one operator decision, then apply it and immediately re-evaluate."""
        if type(enabled) is not bool:
            raise TypeError("enabled must be an exact bool")
        record = self._interlocks.get(interlock_name)
        if record is None:
            raise KeyError(interlock_name)
        if not record.condition.operator_disableable:
            raise PermissionError(interlock_name)
        if type(operator) is not str or not operator.strip():
            raise ValueError("operator must be non-empty")
        if changed_at.tzinfo is None or changed_at.utcoffset() is None:
            raise ValueError("changed_at must be timezone-aware")
        async with self._state_change_lock:
            policy_fingerprint = _interlock_policy_fingerprint(record.condition)
            normalized_changed_at = changed_at.astimezone(UTC).isoformat()
            for retained in record.transition_receipts:
                if retained.get("request_id") != request_id:
                    continue
                retained = _validated_operator_transition_receipt(retained)
                if (
                    retained.get("enabled") is not enabled
                    or retained.get("operator") != operator.strip()
                    or retained.get("changed_at") != normalized_changed_at
                    or retained.get("notice") != notice
                    or retained.get("commit_receipt") != commit_receipt
                    or retained.get("policy_fingerprint") != policy_fingerprint
                ):
                    raise RuntimeError("interlock operator request identity conflict")
                return {
                    "name": interlock_name,
                    "enabled": retained["enabled"],
                    "previous_enabled": retained["previous_enabled"],
                    "operator_disableable": record.condition.operator_disableable,
                    "notice": retained["notice"],
                    "changed_at": retained["changed_at"],
                }
            if len(record.pending_transition_receipts) >= _MAX_PENDING_OPERATOR_TRANSITIONS:
                raise RuntimeError("interlock operator provenance backlog is full")
            if len(record.transition_receipts) >= _MAX_OPERATOR_TRANSITION_RECEIPTS:
                raise RuntimeError("interlock operator idempotency journal is full")
            previous = record.enabled
            receipt = {
                "enabled": enabled,
                "previous_enabled": previous,
                "operator": operator.strip(),
                "changed_at": normalized_changed_at,
                "request_id": request_id,
                "notice": notice,
                "experiment_id": commit_receipt.get("experiment_id"),
                "policy_fingerprint": policy_fingerprint,
                "commit_receipt": dict(commit_receipt),
            }
            receipt = _validated_operator_transition_receipt(receipt)
            pending = [*record.pending_transition_receipts, receipt]
            transitions = [*record.transition_receipts, receipt]
            next_state = self._persistent_operator_states(
                target_name=interlock_name,
                target_enabled=enabled,
                target_receipt=receipt,
                target_pending=pending,
                target_transitions=transitions,
            )

            async def settle_transition() -> dict[str, Any]:
                await asyncio.to_thread(self._write_operator_state, next_state)
                record.enabled = enabled
                record.disable_receipt = None if enabled else receipt
                record.last_transition_receipt = receipt
                record.pending_transition_receipts = pending
                record.transition_receipts = transitions
                if not enabled:
                    record.condition_active = False
                elif not previous:
                    record.state = InterlockState.ARMED
                    for channel in sorted(record.latest_readings):
                        latest = record.latest_readings[channel]
                        if record.condition.is_triggered(latest.value):
                            await self._trip(record, latest)
                            break
                if self._state_changed_handler is not None:
                    result = self._state_changed_handler()
                    if asyncio.iscoroutine(result):
                        await result
                return {
                    "name": interlock_name,
                    "enabled": enabled,
                    "previous_enabled": previous,
                    "operator_disableable": record.condition.operator_disableable,
                    "notice": notice,
                    "changed_at": receipt["changed_at"],
                }

            owner = asyncio.create_task(
                settle_transition(),
                name=f"interlock_operator_transition_{request_id[:8]}",
            )
            return await await_executor_owner(owner)

    async def mark_operator_transition_recorded(self, interlock_name: str, request_id: str) -> bool:
        """Discard one pending receipt only after experiment provenance settles."""
        record = self._interlocks.get(interlock_name)
        if record is None:
            raise KeyError(interlock_name)
        async with self._state_change_lock:
            pending = [
                receipt for receipt in record.pending_transition_receipts if receipt.get("request_id") != request_id
            ]
            if len(pending) == len(record.pending_transition_receipts):
                return False
            next_state = self._persistent_operator_states(
                target_name=interlock_name,
                target_enabled=record.enabled,
                target_receipt=record.last_transition_receipt,
                target_pending=pending,
                target_transitions=record.transition_receipts,
            )
            await asyncio.to_thread(self._write_operator_state, next_state)
            record.pending_transition_receipts = pending
            return True

    async def mark_all_operator_transitions_recorded(self) -> bool:
        """Clear the pending journal after full provenance reconciliation."""
        async with self._state_change_lock:
            if not any(record.pending_transition_receipts for record in self._interlocks.values()):
                return False
            next_state = self._persistent_operator_states(clear_pending=True)
            await asyncio.to_thread(self._write_operator_state, next_state)
            for record in self._interlocks.values():
                record.pending_transition_receipts = []
            return True

    def _load_operator_state(self) -> None:
        path = self._state_path
        if path is None:
            return
        if not path.exists():
            self._write_operator_state({})
            return
        if path.stat().st_size > _MAX_OPERATOR_STATE_BYTES:
            raise InterlockConfigError(f"interlock operator state at {path} exceeds its size bound")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise InterlockConfigError(f"interlock operator state at {path} is unreadable") from exc
        if type(payload) is not dict or set(payload) != {"schema_version", "interlocks", "updated_at"}:
            raise InterlockConfigError(f"interlock operator state at {path} is invalid")
        states = payload.get("interlocks")
        schema_version = payload.get("schema_version")
        updated_at = payload.get("updated_at")
        if schema_version not in (1, 2, 3) or type(states) is not dict or type(updated_at) is not str:
            raise InterlockConfigError(f"interlock operator state at {path} is invalid")
        try:
            parsed_updated_at = datetime.fromisoformat(updated_at)
        except ValueError as exc:
            raise InterlockConfigError(f"interlock operator state at {path} is invalid") from exc
        if parsed_updated_at.tzinfo is None or parsed_updated_at.utcoffset() is None:
            raise InterlockConfigError(f"interlock operator state at {path} is invalid")
        for name, state in states.items():
            if schema_version == 1:
                expected_keys = {"enabled", "receipt"}
            elif schema_version == 2:
                expected_keys = {
                    "enabled",
                    "receipt",
                    "pending_receipts",
                }
            else:
                expected_keys = {
                    "enabled",
                    "receipt",
                    "pending_receipts",
                    "transition_receipts",
                }
            if (
                type(name) is not str
                or not name
                or type(state) is not dict
                or set(state) != expected_keys
                or type(state.get("enabled")) is not bool
                or type(state.get("receipt")) is not dict
                or (
                    schema_version >= 2
                    and (
                        type(state.get("pending_receipts")) is not list
                        or len(state["pending_receipts"]) > _MAX_PENDING_OPERATOR_TRANSITIONS
                        or any(type(receipt) is not dict for receipt in state["pending_receipts"])
                    )
                )
                or (
                    schema_version == 3
                    and (
                        type(state.get("transition_receipts")) is not list
                        or not state["transition_receipts"]
                        or len(state["transition_receipts"]) > _MAX_OPERATOR_TRANSITION_RECEIPTS
                        or any(type(receipt) is not dict for receipt in state["transition_receipts"])
                    )
                )
            ):
                raise InterlockConfigError(f"interlock operator state at {path} is invalid")
            try:
                last_receipt = _validated_operator_transition_receipt(state["receipt"])
                pending_receipts = (
                    []
                    if schema_version == 1
                    else [_validated_operator_transition_receipt(receipt) for receipt in state["pending_receipts"]]
                )
                if schema_version == 3:
                    transition_receipts = [
                        _validated_operator_transition_receipt(receipt) for receipt in state["transition_receipts"]
                    ]
                else:
                    transition_receipts = list(pending_receipts)
                    if not any(receipt["request_id"] == last_receipt["request_id"] for receipt in transition_receipts):
                        transition_receipts.append(last_receipt)
            except (UnicodeError, ValueError) as exc:
                raise InterlockConfigError(f"interlock operator state at {path} is invalid") from exc
            transition_ids = [receipt["request_id"] for receipt in transition_receipts]
            pending_ids = [receipt["request_id"] for receipt in pending_receipts]
            if (
                last_receipt["enabled"] is not state["enabled"]
                or len(set(transition_ids)) != len(transition_ids)
                or len(set(pending_ids)) != len(pending_ids)
                or last_receipt["request_id"] not in transition_ids
                or any(request_id not in transition_ids for request_id in pending_ids)
            ):
                raise InterlockConfigError(f"interlock operator state at {path} is invalid")
            record = self._interlocks.get(name)
            if record is None:
                self._retired_operator_state[name] = {
                    "enabled": state["enabled"],
                    "receipt": last_receipt,
                    "pending_receipts": pending_receipts,
                    "transition_receipts": transition_receipts,
                }
                continue
            if state["enabled"] is False and not record.condition.operator_disableable:
                raise InterlockConfigError(f"persisted disabled interlock {name!r} is no longer operator-disableable")
            if state["enabled"] is False:
                if frozenset(last_receipt) != _OPERATOR_TRANSITION_RECEIPT_KEYS:
                    raise InterlockConfigError(f"persisted disabled interlock {name!r} has no reviewed policy identity")
                if last_receipt["policy_fingerprint"] != _interlock_policy_fingerprint(record.condition):
                    raise InterlockConfigError(
                        f"persisted disabled interlock {name!r} no longer matches its reviewed policy"
                    )
            record.enabled = state["enabled"]
            record.last_transition_receipt = last_receipt
            record.disable_receipt = None if state["enabled"] else dict(last_receipt)
            record.pending_transition_receipts = pending_receipts
            record.transition_receipts = transition_receipts

    async def restore_operator_state(self) -> None:
        """Load or initialize operator state without blocking the engine loop."""
        await asyncio.to_thread(self._load_operator_state)

    def _write_operator_state(self, states: dict[str, dict[str, Any]]) -> None:
        path = self._state_path
        if path is None:
            return
        payload = {
            "schema_version": 3,
            "interlocks": states,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        if len(serialized.encode("utf-8")) > _MAX_OPERATOR_STATE_BYTES:
            raise RuntimeError("interlock operator state exceeds its size bound")
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, serialized)

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
