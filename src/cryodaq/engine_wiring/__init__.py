"""Подсистемные строители и рантайм-задачи движка CryoDAQ.

Монолитный ``engine._run_engine`` развязан: вложенные замыкания вынесены
в импортируемые модульные функции/классы, каждый берёт зависимости явно и
тестируется в изоляции. Пакет НЕ импортирует ``cryodaq.agents`` и его
RAG/LLM-зависимости (safety-процесс остаётся чистым, см. B1).
"""

from cryodaq.engine_wiring.runtime_tasks import (
    alarm_ring_feed,
    alarm_v2_feed_readings,
    alarm_v2_tick,
    assistant_event_relay_loop,
    cold_rotation_scheduler,
    cooldown_alarm_tick_loop,
    leak_rate_feed,
    sensor_diag_feed,
    sensor_diag_tick,
    track_runtime_signals,
    vacuum_guard_tick_loop,
    vacuum_trend_feed,
    vacuum_trend_tick,
)
from cryodaq.engine_wiring.supervision import (
    TaskSupervisor,
    install_loop_exception_backstop,
)

__all__ = [
    "TaskSupervisor",
    "alarm_ring_feed",
    "alarm_v2_feed_readings",
    "alarm_v2_tick",
    "assistant_event_relay_loop",
    "cold_rotation_scheduler",
    "cooldown_alarm_tick_loop",
    "install_loop_exception_backstop",
    "leak_rate_feed",
    "sensor_diag_feed",
    "sensor_diag_tick",
    "track_runtime_signals",
    "vacuum_guard_tick_loop",
    "vacuum_trend_feed",
    "vacuum_trend_tick",
]
