"""Run an external mock instrument for thermal-conductivity checks.

The process owns the thermal model and its ground truth. CryoDAQ receives only
ordinary Lake Shore 218 query replies plus a mock-only heater-power command.

Truth-history contract: the plant retains only the most recent
``TRUTH_HISTORY_MAX_POINTS`` commanded heater points; every truth payload
reports how many older points were dropped (``commanded_points_dropped``) and
how many were ever commanded (``commanded_points_total``), so truncation is
always visible. ``MOCK:TRUTH?`` replies are serialized to a single ASCII line
that never exceeds ``TRUTH_LINE_MAX_BYTES`` bytes including its newline, which
keeps the reply readable for clients that read one line through asyncio's
default 64 KiB stream-reader limit.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import socketserver
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

#: Most recent commanded heater points retained for ground-truth correlation;
#: anything older is reported as dropped rather than growing memory forever.
TRUTH_HISTORY_MAX_POINTS = 128

#: Byte budget (including the newline) for one ``MOCK:TRUTH?`` line; half of
#: asyncio's default StreamReader limit, enforced mechanically when encoding.
TRUTH_LINE_MAX_BYTES = 32768

_LS218_CHANNEL_COUNT = 8


class ThermalPlant:
    """A small nonlinear thermal link with first-order settling."""

    def __init__(
        self,
        *,
        bath_temperature_k: float,
        conductance_w_per_k: float,
        conductance_slope_w_per_k2: float,
        time_constant_s: float,
    ) -> None:
        values = {
            "bath_temperature_k": bath_temperature_k,
            "conductance_w_per_k": conductance_w_per_k,
            "conductance_slope_w_per_k2": conductance_slope_w_per_k2,
            "time_constant_s": time_constant_s,
        }
        for name, value in values.items():
            if isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"{name} must be finite")
        if bath_temperature_k <= 0.0 or conductance_w_per_k <= 0.0 or time_constant_s <= 0.0:
            raise ValueError("bath temperature, conductance, and time constant must be positive")
        if conductance_slope_w_per_k2 < 0.0:
            raise ValueError("conductance slope must be non-negative")
        self.bath_temperature_k = float(bath_temperature_k)
        self.conductance_w_per_k = float(conductance_w_per_k)
        self.conductance_slope_w_per_k2 = float(conductance_slope_w_per_k2)
        self.time_constant_s = float(time_constant_s)
        self._power_w = 0.0
        self._rise_k = 0.0
        self._last_update_s = time.monotonic()
        self._history: deque[dict[str, float]] = deque(maxlen=TRUTH_HISTORY_MAX_POINTS)
        self._commanded_points_total = 0
        self._lock = threading.Lock()

    def _equilibrium_rise(self, power_w: float) -> float:
        slope = self.conductance_slope_w_per_k2
        if slope == 0.0:
            return power_w / self.conductance_w_per_k
        return (math.sqrt(self.conductance_w_per_k**2 + 2.0 * slope * power_w) - self.conductance_w_per_k) / slope

    def _advance_locked(self) -> None:
        now = time.monotonic()
        elapsed_s = max(0.0, now - self._last_update_s)
        equilibrium = self._equilibrium_rise(self._power_w)
        decay = math.exp(-elapsed_s / self.time_constant_s)
        self._rise_k = equilibrium + (self._rise_k - equilibrium) * decay
        self._last_update_s = now

    def set_power(self, power_w: float) -> None:
        if isinstance(power_w, bool) or not math.isfinite(float(power_w)) or float(power_w) < 0.0:
            raise ValueError("power must be finite and non-negative")
        with self._lock:
            self._advance_locked()
            self._power_w = float(power_w)
            rise = self._equilibrium_rise(self._power_w)
            expected_g = self._power_w / rise if rise > 0.0 else self.conductance_w_per_k
            self._history.append(
                {
                    "power_w": self._power_w,
                    "equilibrium_delta_t_k": rise,
                    "expected_g_w_per_k": expected_g,
                }
            )
            self._commanded_points_total += 1

    def temperatures(self) -> tuple[float, ...]:
        with self._lock:
            self._advance_locked()
            hot = self.bath_temperature_k + self._rise_k
            return (hot, self.bath_temperature_k, *([self.bath_temperature_k] * 6))

    def truth(self) -> dict[str, Any]:
        with self._lock:
            self._advance_locked()
            retained = len(self._history)
            return {
                "model": "nonlinear_thermal_link_v1",
                "bath_temperature_k": self.bath_temperature_k,
                "conductance_w_per_k": self.conductance_w_per_k,
                "conductance_slope_w_per_k2": self.conductance_slope_w_per_k2,
                "time_constant_s": self.time_constant_s,
                "commanded_points": list(self._history),
                "commanded_points_total": self._commanded_points_total,
                "commanded_points_dropped": self._commanded_points_total - retained,
            }


def _sensor_unit(temp_k: float) -> float:
    return (1600.0 / (temp_k + 15.0)) + 0.08


def _channel_index(command_upper: str) -> int:
    """Translate a validated ``<CMD>? <channel>`` operand into a 0-based index."""

    operand = command_upper.split(maxsplit=1)[1]
    if len(operand) != 1 or operand not in "12345678":
        raise ValueError(f"invalid LS218 channel operand: {operand!r}")
    try:
        channel = int(operand)
    except ValueError:
        raise ValueError(f"invalid LS218 channel operand: {operand!r}") from None
    if not 1 <= channel <= _LS218_CHANNEL_COUNT:
        raise ValueError(f"LS218 channel {channel} outside valid range 1..{_LS218_CHANNEL_COUNT}")
    return channel - 1


def _truth_response_line(plant: ThermalPlant) -> str:
    """Serialize truth as one ASCII line within :data:`TRUTH_LINE_MAX_BYTES`.

    If even the retained points would not fit, the oldest points are dropped
    from the reply only, and each drop is folded into
    ``commanded_points_dropped`` so truncation is never silent.
    """

    payload = plant.truth()
    points = list(payload.pop("commanded_points"))
    dropped = int(payload.pop("commanded_points_dropped"))
    while True:
        payload["commanded_points"] = points
        payload["commanded_points_dropped"] = dropped
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if len(line.encode("ascii")) + 1 <= TRUTH_LINE_MAX_BYTES or not points:
            return line
        points.pop(0)
        dropped += 1


class SimulatorServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], plant: ThermalPlant) -> None:
        self.plant = plant
        super().__init__(address, SimulatorHandler)

    def response_for(self, command: str) -> str:
        text = command.strip()
        upper = text.upper()
        if upper == "*IDN?":
            return "LSCI,MODEL218S,THERMAL-SIM,1.0"
        if upper == "KRDG?" or upper.startswith("KRDG? "):
            values = self.plant.temperatures()
            if upper != "KRDG?":
                return f"{values[_channel_index(upper)]:+.9E}"
            return ",".join(f"{value:+.9E}" for value in values)
        if upper == "SRDG?" or upper.startswith("SRDG? "):
            values = tuple(_sensor_unit(value) for value in self.plant.temperatures())
            if upper != "SRDG?":
                return f"{values[_channel_index(upper)]:+.9E}"
            return ",".join(f"{value:+.9E}" for value in values)
        if upper.startswith("RDGST? "):
            _channel_index(upper)
            return "0"
        if upper.startswith("MOCK:POWER "):
            self.plant.set_power(float(text.split(maxsplit=1)[1]))
            return "OK"
        if upper == "MOCK:TRUTH?":
            return _truth_response_line(self.plant)
        if upper == "MOCK:SHUTDOWN":
            threading.Thread(target=self.shutdown, daemon=True).start()
            return "OK"
        raise ValueError(f"unsupported command: {text}")


class SimulatorHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(4097)
        if not raw or len(raw) > 4096 or not raw.endswith(b"\n"):
            return
        try:
            command = raw.decode("ascii").strip()
            response = self.server.response_for(command)  # type: ignore[attr-defined]
        except Exception as exc:
            response = f"ERROR {type(exc).__name__}: {exc}"
        self.wfile.write(response.encode("ascii") + b"\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="External CryoDAQ thermal mock instrument")
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost"))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--truth-output", type=Path, required=True)
    parser.add_argument("--bath-temperature-k", type=float, default=4.2)
    parser.add_argument("--conductance-w-per-k", type=float, default=0.1)
    parser.add_argument("--conductance-slope-w-per-k2", type=float, default=0.02)
    parser.add_argument("--time-constant-s", type=float, default=0.25)
    args = parser.parse_args()

    # A reused --ready-file path still holds the previous process's endpoint
    # document because shutdown never removed it, so an existence-polling
    # launcher could read the stale port before this run publishes its own.
    # Clear the stale document before binding so readiness is generation-bound
    # to this process.
    if args.ready_file.is_file():
        args.ready_file.unlink()

    plant = ThermalPlant(
        bath_temperature_k=args.bath_temperature_k,
        conductance_w_per_k=args.conductance_w_per_k,
        conductance_slope_w_per_k2=args.conductance_slope_w_per_k2,
        time_constant_s=args.time_constant_s,
    )
    server = SimulatorServer((args.host, args.port), plant)
    host, port = server.server_address
    _write_json(args.ready_file, {"host": host, "port": port, "protocol": "lake_shore_218_plus_mock_power_v1"})

    def _stop(_signum: int, _frame: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        server.serve_forever(poll_interval=0.05)
    finally:
        server.server_close()
        if args.ready_file.is_file():
            args.ready_file.unlink()
        _write_json(args.truth_output, plant.truth())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
