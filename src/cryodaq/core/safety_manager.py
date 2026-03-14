"""SafetyManager — центральный менеджер безопасности CryoDAQ.

АРХИТЕКТУРА БЕЗОПАСНОСТИ:
- Безопасное состояние (source OFF) — DEFAULT. Работа нагревателя
  требует непрерывного подтверждения, что всё исправно.
- Отсутствие данных = ОПАСНО (fail-on-silence).
- Единственная точка принятия решений о включении/отключении источника.
- Двухшаговое восстановление после аварии.

ДИАГРАММА СОСТОЯНИЙ:

    SAFE_OFF ──(все предусловия ОК)──► READY
                                         │
                         (оператор запросил + проверка) │
                                         ▼
                                    RUN_PERMITTED
                                         │
                            (источник подтверждён ON) │
                                         ▼
                                      RUNNING
                                     │       │
                    (оператор стоп)  │       │ (нарушение)
                         ▼           │       ▼
                     SAFE_OFF       │    FAULT_LATCHED
                                    │       │
                                    │  (оператор + причина)
                                    │       ▼
                                    │   MANUAL_RECOVERY
                                    │       │
                                    │  (предусловия ОК)
                                    │       ▼
                                    └──► READY

    Из ЛЮБОГО состояния:
        → FAULT_LATCHED (критическое нарушение)
        → SAFE_OFF (аварийное отключение)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import yaml

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

_MAX_EVENTS = 500
_CHECK_INTERVAL_S = 1.0


class SafetyState(Enum):
    """Состояние системы безопасности."""

    SAFE_OFF = "safe_off"                 # Источник ВЫКЛЮЧЕН. Стандартное состояние.
    READY = "ready"                       # Все предусловия ОК, оператор может запустить.
    RUN_PERMITTED = "run_permitted"       # Запрос на запуск одобрен, ожидание подтверждения.
    RUNNING = "running"                   # Источник ВКЛЮЧЁН, непрерывный мониторинг.
    FAULT_LATCHED = "fault_latched"       # Авария. Источник ВЫКЛЮЧЕН. Требуется вмешательство.
    MANUAL_RECOVERY = "manual_recovery"   # Оператор подтвердил, система проверяет предусловия.


@dataclass(frozen=True, slots=True)
class SafetyEvent:
    """Запись о событии безопасности."""

    timestamp: datetime
    from_state: SafetyState
    to_state: SafetyState
    reason: str
    channel: str = ""
    value: float = 0.0


@dataclass
class SafetyConfig:
    """Конфигурация безопасности."""

    critical_channels: list[re.Pattern[str]] = field(default_factory=list)
    stale_timeout_s: float = 10.0
    heartbeat_timeout_s: float = 15.0
    max_safety_backlog: int = 100
    require_keithley_for_run: bool = True
    max_dT_dt_K_per_min: float = 5.0
    require_reason: bool = True
    cooldown_before_rearm_s: float = 60.0


class SafetyManager:
    """Центральный менеджер безопасности.

    Единственная точка принятия решений о включении/отключении источника тока.
    Все команды keithley_start/stop проходят через SafetyManager.
    """

    def __init__(
        self,
        safety_broker: SafetyBroker,
        *,
        keithley_driver: Any | None = None,
        mock: bool = False,
    ) -> None:
        self._broker = safety_broker
        self._keithley = keithley_driver
        self._mock = mock
        self._state = SafetyState.SAFE_OFF
        self._config = SafetyConfig()
        self._events: deque[SafetyEvent] = deque(maxlen=_MAX_EVENTS)
        self._fault_reason: str = ""
        self._fault_time: float = 0.0
        self._recovery_reason: str = ""

        # Текущие значения каналов: channel → (monotonic_time, value)
        self._latest: dict[str, tuple[float, float]] = {}
        # Скорости изменения: channel → deque[(monotonic, value)]
        self._rate_buffers: dict[str, deque[tuple[float, float]]] = {}

        self._queue: asyncio.Queue[Reading] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._collect_task: asyncio.Task[None] | None = None

        # Callbacks для уведомлений (GUI, Telegram)
        self._on_state_change: list[Callable[[SafetyState, SafetyState, str], Any]] = []

        # Установить overflow callback на SafetyBroker
        self._broker.set_overflow_callback(
            lambda: self._fault("SafetyBroker переполнен — данные потеряны")
        )

    # ------------------------------------------------------------------
    # Конфигурация
    # ------------------------------------------------------------------

    def load_config(self, path: Path) -> None:
        """Загрузить config/safety.yaml."""
        if not path.exists():
            logger.warning("Файл safety.yaml не найден: %s — используются значения по умолчанию", path)
            return

        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        patterns = []
        for p in raw.get("critical_channels", []):
            try:
                patterns.append(re.compile(p))
            except re.error as exc:
                logger.error("Некорректный regex в critical_channels: '%s': %s", p, exc)

        self._config = SafetyConfig(
            critical_channels=patterns,
            stale_timeout_s=float(raw.get("stale_timeout_s", 10.0)),
            heartbeat_timeout_s=float(raw.get("heartbeat_timeout_s", 15.0)),
            max_safety_backlog=int(raw.get("max_safety_backlog", 100)),
            require_keithley_for_run=bool(raw.get("require_keithley_for_run", True)),
            max_dT_dt_K_per_min=float(raw.get("rate_limits", {}).get("max_dT_dt_K_per_min", 5.0)),
            require_reason=bool(raw.get("recovery", {}).get("require_reason", True)),
            cooldown_before_rearm_s=float(raw.get("recovery", {}).get("cooldown_before_rearm_s", 60.0)),
        )
        logger.info(
            "SafetyManager: конфигурация загружена. Критических каналов: %d, stale=%.0fs",
            len(self._config.critical_channels),
            self._config.stale_timeout_s,
        )

    # ------------------------------------------------------------------
    # Жизненный цикл
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Запустить SafetyManager."""
        self._queue = self._broker.subscribe("safety_manager", maxsize=self._config.max_safety_backlog)
        self._broker.freeze()

        self._collect_task = asyncio.create_task(self._collect_loop(), name="safety_collect")
        self._monitor_task = asyncio.create_task(self._monitor_loop(), name="safety_monitor")

        logger.info(
            "SafetyManager запущен. Состояние: %s. Mock: %s.",
            self._state.value, self._mock,
        )

    async def stop(self) -> None:
        """Остановить SafetyManager. Гарантировать источник OFF."""
        # Сначала убедимся, что источник выключен
        if self._state == SafetyState.RUNNING:
            await self._safe_off("Остановка системы")

        for task in (self._collect_task, self._monitor_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._collect_task = None
        self._monitor_task = None
        logger.info("SafetyManager остановлен. Финальное состояние: %s.", self._state.value)

    # ------------------------------------------------------------------
    # Публичный API (вызывается из GUI через ZMQ command handler)
    # ------------------------------------------------------------------

    @property
    def state(self) -> SafetyState:
        return self._state

    @property
    def fault_reason(self) -> str:
        return self._fault_reason

    async def request_run(
        self, p_target: float, v_comp: float, i_comp: float,
    ) -> dict[str, Any]:
        """Оператор запрашивает включение источника.

        Возвращает {"ok": True/False, "state": ..., "error": ...}.
        """
        if self._state == SafetyState.FAULT_LATCHED:
            return {"ok": False, "state": self._state.value,
                    "error": f"FAULT: {self._fault_reason}"}

        if self._state not in (SafetyState.SAFE_OFF, SafetyState.READY):
            return {"ok": False, "state": self._state.value,
                    "error": f"Запуск невозможен из состояния {self._state.value}"}

        # Проверить предусловия
        ok, reason = self._check_preconditions()
        if not ok:
            return {"ok": False, "state": self._state.value, "error": reason}

        # Перейти в RUN_PERMITTED
        self._transition(SafetyState.RUN_PERMITTED, f"Запуск запрошен: P={p_target}W")

        # Попытка запустить источник
        if self._keithley is None:
            if self._config.require_keithley_for_run and not self._mock:
                self._transition(SafetyState.SAFE_OFF, "Keithley не подключён")
                return {"ok": False, "state": self._state.value,
                        "error": "Keithley не подключён"}
            # Mock mode — имитируем успех
            self._transition(SafetyState.RUNNING, f"Mock RUN: P={p_target}W")
            return {"ok": True, "state": self._state.value}

        try:
            await self._keithley.start_source(p_target, v_comp, i_comp)
            self._transition(SafetyState.RUNNING, f"Источник включён: P={p_target}W")
            return {"ok": True, "state": self._state.value}
        except Exception as exc:
            await self._fault(f"Ошибка запуска источника: {exc}")
            return {"ok": False, "state": self._state.value, "error": str(exc)}

    async def request_stop(self) -> dict[str, Any]:
        """Оператор запрашивает штатную остановку."""
        await self._safe_off("Штатная остановка оператором")
        return {"ok": True, "state": self._state.value}

    async def emergency_off(self) -> dict[str, Any]:
        """Аварийное отключение. Bypasses state machine — прямое отключение."""
        logger.critical("АВАРИЙНОЕ ОТКЛЮЧЕНИЕ — прямая команда")
        if self._keithley is not None:
            try:
                await self._keithley.emergency_off()
            except Exception as exc:
                logger.critical("Ошибка emergency_off: %s", exc)
        self._transition(SafetyState.SAFE_OFF, "Аварийное отключение оператором")
        return {"ok": True, "state": self._state.value}

    async def acknowledge_fault(self, reason: str) -> dict[str, Any]:
        """Оператор подтверждает аварию и указывает причину.

        Step 1 восстановления: FAULT_LATCHED → MANUAL_RECOVERY.
        """
        if self._state != SafetyState.FAULT_LATCHED:
            return {"ok": False, "state": self._state.value,
                    "error": "Нет активной аварии для подтверждения"}

        if self._config.require_reason and not reason.strip():
            return {"ok": False, "state": self._state.value,
                    "error": "Укажите причину аварии"}

        # Cooldown check
        elapsed = time.monotonic() - self._fault_time
        if elapsed < self._config.cooldown_before_rearm_s:
            remaining = self._config.cooldown_before_rearm_s - elapsed
            return {"ok": False, "state": self._state.value,
                    "error": f"Ожидание: ещё {remaining:.0f}с до разрешения восстановления"}

        self._recovery_reason = reason.strip()
        self._transition(
            SafetyState.MANUAL_RECOVERY,
            f"Оператор подтвердил аварию: {reason}",
        )
        return {"ok": True, "state": self._state.value}

    def get_status(self) -> dict[str, Any]:
        """Полный статус для GUI / Telegram."""
        return {
            "state": self._state.value,
            "fault_reason": self._fault_reason,
            "recovery_reason": self._recovery_reason,
            "channels_tracked": len(self._latest),
            "keithley_connected": self._keithley is not None and (
                self._keithley.connected if hasattr(self._keithley, "connected") else False
            ),
            "mock": self._mock,
        }

    def get_events(self) -> list[SafetyEvent]:
        return list(self._events)

    def on_state_change(self, callback: Callable) -> None:
        """Зарегистрировать callback(from_state, to_state, reason)."""
        self._on_state_change.append(callback)

    # ------------------------------------------------------------------
    # Внутренние переходы
    # ------------------------------------------------------------------

    def _transition(self, new_state: SafetyState, reason: str) -> None:
        """Выполнить переход состояния с логированием и уведомлением."""
        old = self._state
        self._state = new_state

        event = SafetyEvent(
            timestamp=datetime.now(timezone.utc),
            from_state=old,
            to_state=new_state,
            reason=reason,
        )
        self._events.append(event)

        level = logging.CRITICAL if new_state == SafetyState.FAULT_LATCHED else logging.INFO
        logger.log(
            level,
            "SAFETY: %s → %s | %s",
            old.value, new_state.value, reason,
        )

        for cb in self._on_state_change:
            try:
                cb(old, new_state, reason)
            except Exception:
                logger.exception("Ошибка в safety state_change callback")

    async def _fault(self, reason: str, *, channel: str = "", value: float = 0.0) -> None:
        """Перевести в FAULT_LATCHED + emergency_off."""
        self._fault_reason = reason
        self._fault_time = time.monotonic()

        # Немедленное отключение источника
        if self._keithley is not None:
            try:
                await self._keithley.emergency_off()
            except Exception as exc:
                logger.critical("FAULT: emergency_off FAILED: %s", exc)

        self._transition(SafetyState.FAULT_LATCHED, reason)

    async def _safe_off(self, reason: str) -> None:
        """Штатный переход в SAFE_OFF + остановка источника."""
        if self._keithley is not None and self._state == SafetyState.RUNNING:
            try:
                await self._keithley.stop_source()
            except Exception as exc:
                logger.error("Ошибка stop_source: %s", exc)

        self._transition(SafetyState.SAFE_OFF, reason)

    # ------------------------------------------------------------------
    # Предусловия
    # ------------------------------------------------------------------

    def _check_preconditions(self) -> tuple[bool, str]:
        """Проверить все предусловия для перехода в READY/RUN.

        Возвращает (ok, reason).
        """
        now = time.monotonic()

        # 1. Критические каналы — свежие данные
        for pattern in self._config.critical_channels:
            matched = False
            for ch, (ts, _val) in self._latest.items():
                if pattern.match(ch):
                    matched = True
                    age = now - ts
                    if age > self._config.stale_timeout_s:
                        return False, f"Устаревшие данные: {ch} ({age:.1f}s > {self._config.stale_timeout_s}s)"
            if not matched and not self._mock:
                return False, f"Нет данных для критического канала: {pattern.pattern}"

        # 2. Keithley подключён (если требуется)
        if self._config.require_keithley_for_run and not self._mock:
            if self._keithley is None:
                return False, "Keithley не подключён"
            if hasattr(self._keithley, "connected") and not self._keithley.connected:
                return False, "Keithley не подключён (connected=False)"

        # 3. Нет активного FAULT
        if self._state == SafetyState.FAULT_LATCHED:
            return False, f"Активная авария: {self._fault_reason}"

        return True, ""

    # ------------------------------------------------------------------
    # Фоновые задачи
    # ------------------------------------------------------------------

    async def _collect_loop(self) -> None:
        """Собирать данные из SafetyBroker."""
        assert self._queue is not None
        try:
            while True:
                reading = await self._queue.get()
                now = time.monotonic()
                self._latest[reading.channel] = (now, reading.value)

                # Буфер скоростей для rate limit check
                if reading.channel not in self._rate_buffers:
                    self._rate_buffers[reading.channel] = deque(maxlen=120)
                self._rate_buffers[reading.channel].append((now, reading.value))
        except asyncio.CancelledError:
            return

    async def _monitor_loop(self) -> None:
        """Непрерывный мониторинг (1 Гц)."""
        try:
            while True:
                await asyncio.sleep(_CHECK_INTERVAL_S)
                await self._run_checks()
        except asyncio.CancelledError:
            return

    async def _run_checks(self) -> None:
        """Выполнить все проверки безопасности."""
        now = time.monotonic()

        # В состоянии MANUAL_RECOVERY — проверяем предусловия для READY
        if self._state == SafetyState.MANUAL_RECOVERY:
            ok, reason = self._check_preconditions()
            if ok:
                self._transition(SafetyState.READY, "Предусловия восстановлены после аварии")
            return

        # Переход SAFE_OFF → READY если все предусловия ОК
        if self._state == SafetyState.SAFE_OFF:
            ok, _ = self._check_preconditions()
            if ok and self._latest:  # Хотя бы один канал получен
                self._transition(SafetyState.READY, "Все предусловия выполнены")
            return

        # В RUNNING — непрерывный мониторинг
        if self._state != SafetyState.RUNNING:
            return

        # 1. Staleness check
        for pattern in self._config.critical_channels:
            for ch, (ts, _val) in self._latest.items():
                if pattern.match(ch):
                    age = now - ts
                    if age > self._config.stale_timeout_s:
                        await self._fault(
                            f"Устаревшие данные канала {ch}: {age:.1f}s без обновления",
                            channel=ch,
                        )
                        return

        # 2. Rate-of-change check
        for ch, buf in self._rate_buffers.items():
            if len(buf) < 10:
                continue
            t0, v0 = buf[0]
            t1, v1 = buf[-1]
            dt_s = t1 - t0
            if dt_s > 0:
                rate_k_min = abs(v1 - v0) / (dt_s / 60.0)
                if rate_k_min > self._config.max_dT_dt_K_per_min:
                    await self._fault(
                        f"Скорость изменения {ch}: {rate_k_min:.2f} К/мин > "
                        f"{self._config.max_dT_dt_K_per_min} К/мин",
                        channel=ch, value=rate_k_min,
                    )
                    return

    # ------------------------------------------------------------------
    # Для InterlockEngine
    # ------------------------------------------------------------------

    async def on_interlock_trip(self, interlock_name: str, channel: str, value: float) -> None:
        """Вызывается InterlockEngine при срабатывании блокировки.

        SafetyManager берёт на себя выполнение действия (emergency_off).
        """
        await self._fault(
            f"Блокировка '{interlock_name}' сработала: канал={channel}, значение={value:.4g}",
            channel=channel, value=value,
        )
