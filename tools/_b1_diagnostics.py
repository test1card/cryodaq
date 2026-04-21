from __future__ import annotations

import time
from typing import Any

from tools._zmq_helpers import DEFAULT_CMD_ADDR, send_command


def _age(now: float, ts: float) -> float | None:
    if ts == 0.0:
        return None
    return max(0.0, round(now - ts, 3))


def bridge_snapshot(bridge: Any, *, now: float | None = None) -> dict[str, Any]:
    now = time.monotonic() if now is None else now
    return {
        "bridge_alive": bridge.is_alive(),
        "bridge_healthy": bridge.is_healthy(),
        "heartbeat_stale": bridge.heartbeat_stale(),
        "data_flow_stalled": bridge.data_flow_stalled(),
        "command_channel_stalled": bridge.command_channel_stalled(),
        "restart_count": bridge.restart_count(),
        "last_heartbeat_age_s": _age(now, getattr(bridge, "_last_heartbeat", 0.0)),
        "last_reading_age_s": _age(now, getattr(bridge, "_last_reading_time", 0.0)),
        "last_cmd_timeout_age_s": _age(now, getattr(bridge, "_last_cmd_timeout", 0.0)),
    }


def direct_engine_probe(
    *,
    address: str = DEFAULT_CMD_ADDR,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    return send_command({"cmd": "safety_status"}, address=address, timeout_s=timeout_s)
