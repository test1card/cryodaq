"""Engine subsystem builders with lazy compatibility exports.

Importing this package is intentionally inert.  Pure leaf contracts such as
``operator_snapshot_authorities`` must not activate runtime-task imports (and
their scheduler/driver dependency graph) merely because Python initializes the
parent package.  Existing package-level names remain available through PEP 562
lazy lookup.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "TaskSupervisor": "cryodaq.engine_wiring.supervision",
    "install_loop_exception_backstop": "cryodaq.engine_wiring.supervision",
    "alarm_ring_feed": "cryodaq.engine_wiring.runtime_tasks",
    "alarm_v2_feed_readings": "cryodaq.engine_wiring.runtime_tasks",
    "alarm_v2_tick": "cryodaq.engine_wiring.runtime_tasks",
    "assistant_event_relay_loop": "cryodaq.engine_wiring.runtime_tasks",
    "cold_rotation_scheduler": "cryodaq.engine_wiring.runtime_tasks",
    "cooldown_alarm_tick_loop": "cryodaq.engine_wiring.runtime_tasks",
    "leak_rate_feed": "cryodaq.engine_wiring.runtime_tasks",
    "sensor_diag_feed": "cryodaq.engine_wiring.runtime_tasks",
    "sensor_diag_tick": "cryodaq.engine_wiring.runtime_tasks",
    "track_runtime_signals": "cryodaq.engine_wiring.runtime_tasks",
    "vacuum_guard_tick_loop": "cryodaq.engine_wiring.runtime_tasks",
    "vacuum_trend_feed": "cryodaq.engine_wiring.runtime_tasks",
    "vacuum_trend_tick": "cryodaq.engine_wiring.runtime_tasks",
}

__all__ = sorted(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
