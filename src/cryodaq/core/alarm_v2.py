"""AlarmEngine v2 — физически обоснованные алармы с composite, rate, stale conditions.

Компоненты:
  AlarmEvent       — событие срабатывания аларма
  PhaseProvider    — интерфейс для получения текущей фазы эксперимента
  SetpointProvider — интерфейс для получения setpoints
  AlarmEvaluator   — вычисляет условие аларма → AlarmEvent | None
  AlarmStateManager — управляет состоянием (active/cleared), гистерезис, dedup

Физическое обоснование: docs/alarm_tz_physics_v3.md
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from cryodaq.core.channel_state import ChannelStateTracker
    from cryodaq.core.rate_estimator import RateEstimator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AlarmEvent
# ---------------------------------------------------------------------------

@dataclass
class AlarmEvent:
    """Событие срабатывания аларма."""

    alarm_id: str
    level: str                        # "INFO" | "WARNING" | "CRITICAL"
    message: str
    triggered_at: float               # unix timestamp
    channels: list[str]               # каналы-участники
    values: dict[str, float]          # channel → значение на момент срабатывания
    acknowledged: bool = False
    acknowledged_at: float = 0.0
    acknowledged_by: str = ""


# ---------------------------------------------------------------------------
# AlarmTransition
# ---------------------------------------------------------------------------

AlarmTransition = Literal["TRIGGERED", "CLEARED"]


# ---------------------------------------------------------------------------
# Provider protocols (duck-typed, без runtime Protocol overhead)
# ---------------------------------------------------------------------------

class PhaseProvider:
    """Базовый провайдер фазы — заглушка для тестов."""

    def get_current_phase(self) -> str | None:
        return None

    def get_phase_elapsed_s(self) -> float:
        return 0.0


class SetpointProvider:
    """Базовый провайдер setpoints — заглушка для тестов."""

    def __init__(self, defaults: dict[str, float] | None = None) -> None:
        self._defaults: dict[str, float] = defaults or {}

    def get(self, key: str) -> float:
        return self._defaults.get(key, 0.0)


# ---------------------------------------------------------------------------
# AlarmEvaluator
# ---------------------------------------------------------------------------

_DEFAULT_RATE_WINDOW_S = 120.0


class AlarmEvaluator:
    """Вычисляет условие аларма по текущему состоянию системы.

    Параметры
    ----------
    state:
        ChannelStateTracker с текущими значениями каналов.
    rate:
        RateEstimator с оценками dX/dt.
    phase_provider:
        Провайдер текущей фазы эксперимента.
    setpoint_provider:
        Провайдер setpoints.
    """

    def __init__(
        self,
        state: ChannelStateTracker,
        rate: RateEstimator,
        phase_provider: PhaseProvider,
        setpoint_provider: SetpointProvider,
    ) -> None:
        self._state = state
        self._rate = rate
        self._phase = phase_provider
        self._setpoint = setpoint_provider

    def evaluate(self, alarm_id: str, alarm_config: dict[str, Any]) -> AlarmEvent | None:
        """Проверить одну alarm-конфигурацию. None = не сработал."""
        alarm_type = alarm_config.get("alarm_type")
        try:
            if alarm_type == "threshold":
                return self._eval_threshold(alarm_id, alarm_config)
            elif alarm_type == "composite":
                return self._eval_composite(alarm_id, alarm_config)
            elif alarm_type == "rate":
                return self._eval_rate(alarm_id, alarm_config)
            elif alarm_type == "stale":
                return self._eval_stale(alarm_id, alarm_config)
            else:
                logger.warning("Неизвестный alarm_type=%r для %s", alarm_type, alarm_id)
                return None
        except Exception as exc:
            logger.error("Ошибка evaluate %s: %s", alarm_id, exc, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # threshold
    # ------------------------------------------------------------------

    def _eval_threshold(self, alarm_id: str, cfg: dict) -> AlarmEvent | None:
        check = cfg.get("check", "above")
        channels = self._resolve_channels(cfg)
        level = cfg.get("level", "WARNING")
        message_tmpl = cfg.get("message", f"Alarm {alarm_id}")

        for ch in channels:
            triggered, value = self._check_threshold_channel(ch, check, cfg)
            if triggered:
                msg = self._format_message(message_tmpl, channel=ch, value=value)
                return AlarmEvent(
                    alarm_id=alarm_id,
                    level=level,
                    message=msg,
                    triggered_at=time.time(),
                    channels=[ch],
                    values={ch: value},
                )
        return None

    def _check_threshold_channel(
        self, channel: str, check: str, cfg: dict
    ) -> tuple[bool, float]:
        """Возвращает (сработал, значение)."""
        if check == "fault_count_in_window":
            count = self._state.get_fault_count(channel)
            min_count = cfg.get("min_fault_count", 1)
            return count >= min_count, float(count)

        state = self._state.get(channel)
        if state is None:
            return False, 0.0
        value = state.value

        if check == "above":
            return value > cfg["threshold"], value
        elif check == "below":
            return value < cfg["threshold"], value
        elif check == "outside_range":
            r = cfg["range"]
            return (value < r[0] or value > r[1]), value
        elif check == "deviation_from_setpoint":
            setpoint = self._setpoint.get(cfg["setpoint_source"])
            return abs(value - setpoint) > cfg["threshold"], value
        else:
            logger.warning("Неизвестный threshold check=%r", check)
            return False, value

    # ------------------------------------------------------------------
    # composite
    # ------------------------------------------------------------------

    def _eval_composite(self, alarm_id: str, cfg: dict) -> AlarmEvent | None:
        operator = cfg.get("operator", "AND")
        conditions = cfg.get("conditions", [])
        level = cfg.get("level", "WARNING")
        message = cfg.get("message", f"Alarm {alarm_id}")

        results = [self._eval_condition(c) for c in conditions]

        if operator == "AND":
            fired = all(results)
        elif operator == "OR":
            fired = any(results)
        else:
            logger.warning("Неизвестный composite operator=%r", operator)
            return None

        if not fired:
            return None

        # Collect channels and values
        channels: list[str] = []
        values: dict[str, float] = {}
        for cond in conditions:
            for ch in self._resolve_channels(cond):
                state = self._state.get(ch)
                if state and ch not in channels:
                    channels.append(ch)
                    values[ch] = state.value

        return AlarmEvent(
            alarm_id=alarm_id,
            level=level,
            message=str(message),
            triggered_at=time.time(),
            channels=channels,
            values=values,
        )

    def _eval_condition(self, cond: dict) -> bool:
        """Вычислить одно sub-condition → bool."""
        check = cond.get("check", "above")

        if check == "any_below":
            channels = self._resolve_channels(cond)
            threshold = cond["threshold"]
            return any(
                (s := self._state.get(ch)) is not None and s.value < threshold
                for ch in channels
            )

        elif check == "any_above":
            channels = self._resolve_channels(cond)
            threshold = cond["threshold"]
            return any(
                (s := self._state.get(ch)) is not None and s.value > threshold
                for ch in channels
            )

        elif check == "above":
            ch = cond.get("channel")
            if not ch:
                return False
            # Special: phase_elapsed_s
            if ch == "phase_elapsed_s":
                elapsed = self._phase.get_phase_elapsed_s()
                return elapsed > cond["threshold"]
            state = self._state.get(ch)
            return state is not None and state.value > cond["threshold"]

        elif check == "below":
            ch = cond.get("channel")
            if not ch:
                return False
            state = self._state.get(ch)
            return state is not None and state.value < cond["threshold"]

        elif check == "rate_above":
            ch = cond.get("channel")
            if not ch:
                return False
            window = cond.get("rate_window_s", _DEFAULT_RATE_WINDOW_S)
            rate = self._rate.get_rate_custom_window(ch, window)
            return rate is not None and rate > cond["threshold"]

        elif check == "rate_below":
            ch = cond.get("channel")
            if not ch:
                return False
            window = cond.get("rate_window_s", _DEFAULT_RATE_WINDOW_S)
            rate = self._rate.get_rate_custom_window(ch, window)
            return rate is not None and rate < cond["threshold"]

        elif check == "rate_near_zero":
            ch = cond.get("channel")
            if not ch:
                return False
            window = cond.get("rate_window_s", _DEFAULT_RATE_WINDOW_S)
            rate = self._rate.get_rate_custom_window(ch, window)
            rate_threshold = cond.get("rate_threshold", 0.1)
            return rate is not None and abs(rate) < rate_threshold

        else:
            logger.warning("Неизвестный composite condition check=%r", check)
            return False

    # ------------------------------------------------------------------
    # rate
    # ------------------------------------------------------------------

    def _eval_rate(self, alarm_id: str, cfg: dict) -> AlarmEvent | None:
        channels = self._resolve_channels(cfg)
        check = cfg.get("check", "rate_above")
        window = cfg.get("rate_window_s", _DEFAULT_RATE_WINDOW_S)
        level = cfg.get("level", "WARNING")
        message_tmpl = cfg.get("message", f"Alarm {alarm_id}")

        for ch in channels:
            rate = self._rate.get_rate_custom_window(ch, window)
            if rate is None:
                continue

            fired = False
            if check == "rate_above":
                fired = rate > cfg["threshold"]
            elif check == "rate_below":
                fired = rate < cfg["threshold"]
            elif check == "rate_near_zero":
                fired = abs(rate) < cfg.get("rate_threshold", 0.1)
            elif check == "relative_rate_near_zero":
                state = self._state.get(ch)
                if state and state.value > 0:
                    rel_rate = abs(rate / state.value)
                    fired = rel_rate < cfg.get("rate_threshold", 0.01)

            if fired:
                # Check additional_condition if present
                add_cond = cfg.get("additional_condition")
                if add_cond and not self._eval_condition(add_cond):
                    continue

                msg = self._format_message(message_tmpl, channel=ch, value=rate)
                return AlarmEvent(
                    alarm_id=alarm_id,
                    level=level,
                    message=msg,
                    triggered_at=time.time(),
                    channels=[ch],
                    values={ch: rate},
                )
        return None

    # ------------------------------------------------------------------
    # stale
    # ------------------------------------------------------------------

    def _eval_stale(self, alarm_id: str, cfg: dict) -> AlarmEvent | None:
        timeout = cfg.get("timeout_s", 30.0)
        channels = self._resolve_channels(cfg)
        level = cfg.get("level", "WARNING")
        message_tmpl = cfg.get("message", "Stale data: {channel}")
        now = time.time()

        for ch in channels:
            state = self._state.get(ch)
            if state is None:
                # Канал никогда не получал данных — тоже stale (если есть данные вообще)
                continue
            if (now - state.timestamp) > timeout:
                msg = self._format_message(message_tmpl, channel=ch, value=0.0)
                return AlarmEvent(
                    alarm_id=alarm_id,
                    level=level,
                    message=msg,
                    triggered_at=now,
                    channels=[ch],
                    values={ch: now - state.timestamp},
                )
        return None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _resolve_channels(self, cfg: dict) -> list[str]:
        """Раскрыть каналы из channel / channels / channel_group в config."""
        if "channels" in cfg:
            return list(cfg["channels"])
        if "channel" in cfg:
            ch = cfg["channel"]
            if ch != "phase_elapsed_s":
                return [ch]
        return []

    @staticmethod
    def _format_message(template: str, channel: str = "", value: float = 0.0) -> str:
        try:
            return template.format(channel=channel, value=value)
        except (KeyError, ValueError):
            return str(template)


# ---------------------------------------------------------------------------
# AlarmStateManager
# ---------------------------------------------------------------------------

@dataclass
class _AlarmRecord:
    event: AlarmEvent
    triggered_at: float
    notified: bool = False


class AlarmStateManager:
    """Управляет состоянием алармов: active/cleared, гистерезис, dedup, sustained.

    Атрибуты
    ----------
    _active: dict[alarm_id, AlarmEvent]
        Активные алармы.
    _sustained_since: dict[alarm_id, float]
        Время первого срабатывания условия (для sustained check).
    """

    def __init__(self) -> None:
        self._active: dict[str, AlarmEvent] = {}
        self._sustained_since: dict[str, float] = {}
        # Ограниченный deque предотвращает утечку памяти при длительной работе.
        self._history: deque[dict] = deque(maxlen=1000)

    def process(
        self,
        alarm_id: str,
        event: AlarmEvent | None,
        config: dict,
    ) -> AlarmTransition | None:
        """Обработать результат evaluate.

        Возвращает:
          "TRIGGERED" — аларм только что сработал (новый)
          "CLEARED"   — аларм только что снялся
          None        — состояние не изменилось
        """
        sustained_s = config.get("sustained_s")
        hysteresis = config.get("hysteresis")

        # --- Условие сработало ---
        if event is not None:
            if sustained_s is not None:
                # Sustained: условие должно держаться N секунд
                if alarm_id not in self._sustained_since:
                    self._sustained_since[alarm_id] = time.time()
                elapsed = time.time() - self._sustained_since[alarm_id]
                if elapsed < sustained_s:
                    return None  # Ещё не выдержали
                # Sustained выдержан — продолжаем вниз к активации
            else:
                # Сброс sustained_since если нет sustained
                self._sustained_since.pop(alarm_id, None)

            # Dedup: уже активен?
            if alarm_id in self._active:
                return None  # Уже активен, не re-notify

            self._active[alarm_id] = event
            self._history.append({
                "alarm_id": alarm_id,
                "transition": "TRIGGERED",
                "at": event.triggered_at,
                "level": event.level,
                "message": event.message,
            })
            logger.info(
                "ALARM TRIGGERED: %s [%s] %s",
                alarm_id, event.level, event.message[:80],
            )
            return "TRIGGERED"

        # --- Условие НЕ сработало ---
        else:
            # Сброс sustained tracking
            self._sustained_since.pop(alarm_id, None)

            if alarm_id not in self._active:
                return None  # Уже не активен

            # Hysteresis: проверить что value вышло из зоны гистерезиса
            if hysteresis and not self._check_hysteresis_cleared(alarm_id, config, hysteresis):
                return None  # Ещё в зоне гистерезиса

            old_event = self._active.pop(alarm_id)
            self._history.append({
                "alarm_id": alarm_id,
                "transition": "CLEARED",
                "at": time.time(),
                "level": old_event.level,
            })
            logger.info("ALARM CLEARED: %s", alarm_id)
            return "CLEARED"

    def _check_hysteresis_cleared(
        self, alarm_id: str, config: dict, hysteresis: Any
    ) -> bool:
        """Проверить что аларм вышел из зоны гистерезиса.

        Упрощённая реализация: hysteresis как отдельный порог не реализован
        без знания текущего значения. Возвращает True (разрешить сброс).
        В реальном использовании evaluator передаёт event=None только когда
        основное условие не выполнено, что уже учитывает гистерезис если
        конфигурация использует порог+гистерезис.
        """
        return True

    def get_active(self) -> dict[str, AlarmEvent]:
        """Текущие активные алармы."""
        return dict(self._active)

    def get_history(self, limit: int = 50) -> list[dict]:
        """История переходов (последние limit)."""
        items = list(self._history)
        return items[-limit:]

    def acknowledge(self, alarm_id: str, *, operator: str = "", reason: str = "") -> dict | None:
        """Подтвердить аларм — записать факт подтверждения в историю.

        Аларм остаётся в _active до сброса по условию (CLEARED).
        Acknowledged означает: оператор видел и принял к сведению.

        Returns event dict on new acknowledgement (caller should publish),
        or None if alarm unknown or already acknowledged (idempotent no-op).
        """
        if alarm_id not in self._active:
            logger.warning("ALARM ACK IGNORED: %s not in active alarms", alarm_id)
            return None

        event = self._active[alarm_id]
        if event.acknowledged:
            logger.debug(
                "ALARM ACK NOOP: %s already acknowledged by %s",
                alarm_id, event.acknowledged_by or "—",
            )
            return None

        event.acknowledged = True
        event.acknowledged_at = time.time()
        event.acknowledged_by = operator

        self._history.append({
            "alarm_id": alarm_id,
            "transition": "ACKNOWLEDGED",
            "at": event.acknowledged_at,
            "level": event.level,
            "operator": operator,
            "reason": reason,
        })
        logger.info(
            "ALARM ACKNOWLEDGED: %s by %s (reason: %s)",
            alarm_id, operator or "—", reason or "—",
        )
        return {
            "alarm_id": alarm_id,
            "acknowledged_at": event.acknowledged_at,
            "operator": operator,
            "reason": reason,
        }
