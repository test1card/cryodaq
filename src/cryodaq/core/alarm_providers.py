"""Конкретные реализации PhaseProvider и SetpointProvider для alarm engine v2.

ExperimentPhaseProvider  — читает фазу из ExperimentManager
ExperimentSetpointProvider — читает setpoints из метаданных эксперимента

Используются при инициализации AlarmEvaluator в engine.py.
"""

from __future__ import annotations

import time
from datetime import UTC
from typing import TYPE_CHECKING

from cryodaq.core.alarm_v2 import PhaseProvider, SetpointProvider

if TYPE_CHECKING:
    from cryodaq.core.alarm_config import SetpointDef
    from cryodaq.core.experiment import ExperimentManager


# ---------------------------------------------------------------------------
# PhaseProvider
# ---------------------------------------------------------------------------

class ExperimentPhaseProvider(PhaseProvider):
    """Читает текущую фазу из ExperimentManager.

    Параметры
    ----------
    experiment_manager:
        Экземпляр ExperimentManager из engine.
    """

    def __init__(self, experiment_manager: ExperimentManager) -> None:
        self._mgr = experiment_manager

    def get_current_phase(self) -> str | None:
        """Текущая фаза активного эксперимента, или None."""
        return self._mgr.get_current_phase()

    def get_phase_elapsed_s(self) -> float:
        """Время с начала текущей фазы, в секундах. 0 если нет фазы."""
        active = self._mgr.get_active_experiment()
        if active is None:
            return 0.0
        history = self._mgr.get_phase_history()
        if not history:
            return 0.0
        # Последняя запись в истории — текущая фаза
        last = history[-1]
        started_at_raw = last.get("started_at")
        if not started_at_raw:
            return 0.0
        # started_at хранится как ISO string
        from datetime import datetime
        try:
            if isinstance(started_at_raw, str):
                dt = datetime.fromisoformat(started_at_raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return time.time() - dt.timestamp()
        except (ValueError, TypeError):
            return 0.0
        return 0.0


# ---------------------------------------------------------------------------
# SetpointProvider
# ---------------------------------------------------------------------------

class ExperimentSetpointProvider(SetpointProvider):
    """Читает setpoints из метаданных эксперимента.

    Для source=="experiment_metadata" ищет значение в custom_fields
    активного эксперимента. Fallback — default из SetpointDef.

    Параметры
    ----------
    experiment_manager:
        Экземпляр ExperimentManager из engine.
    setpoint_defs:
        Словарь определений setpoints из EngineConfig.setpoints.
    """

    def __init__(
        self,
        experiment_manager: ExperimentManager,
        setpoint_defs: dict[str, SetpointDef] | None = None,
    ) -> None:
        super().__init__()
        self._mgr = experiment_manager
        self._defs: dict[str, SetpointDef] = setpoint_defs or {}

    def get(self, key: str) -> float:
        """Получить значение setpoint по ключу.

        Порядок:
        1. Если source=="experiment_metadata" → custom_fields активного эксперимента
        2. Иначе — default из SetpointDef
        3. Если ключ не определён → 0.0
        """
        sp_def = self._defs.get(key)
        if sp_def is None:
            # Попытка прочитать напрямую из _defaults (базовый класс)
            return self._defaults.get(key, 0.0)

        if sp_def.source == "experiment_metadata":
            active = self._mgr.get_active_experiment()
            if active is not None:
                custom_val = active.custom_fields.get(key)
                if custom_val is not None:
                    try:
                        return float(custom_val)
                    except (ValueError, TypeError):
                        pass

        return sp_def.default
