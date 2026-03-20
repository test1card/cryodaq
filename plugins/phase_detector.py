"""Phase Detector — automatic experiment phase detection.

Analyzes dT/dt of the primary temperature channel and pressure trends
to suggest the current experiment phase. Read-only: does not transition
phases automatically. Publishes DerivedMetric for GUI display.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from typing import Any

from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric
from cryodaq.drivers.base import ChannelStatus, Reading

_log = logging.getLogger(__name__)

_PHASE_CODES: dict[str, float] = {
    "unknown": 0.0,
    "preparation": 1.0,
    "vacuum": 2.0,
    "cooldown": 3.0,
    "measurement": 4.0,
    "warmup": 5.0,
    "teardown": 6.0,
}


class PhaseDetector(AnalyticsPlugin):
    """Detect experiment phase from temperature and pressure trends.

    Config (YAML):
        temperature_channel: str — primary temp sensor channel name
        pressure_channel: str — vacuum gauge channel name (optional)
        target_T_K: float — measurement target temperature (default 4.2)
        stabilization_tolerance_K: float — max deviation from target (default 0.1)
        stabilization_window_s: float — how long T must be stable (default 120)
        cooldown_rate_threshold: float — dT/dt below this = cooldown (K/min, default -0.1)
        warmup_rate_threshold: float — dT/dt above this = warmup (K/min, default 0.1)
        room_temp_K: float — above this = preparation/teardown (default 280)
        rate_window_s: float — window for dT/dt computation (default 120)
        pump_rate_threshold: float — dlog10P/dt below this = vacuum (log10(mbar)/min, default -0.01)
    """

    plugin_id = "phase_detector"

    def __init__(self) -> None:
        super().__init__(self.plugin_id)

        self._temp_channel: str = ""
        self._pressure_channel: str = ""
        self._target_T: float = 4.2
        self._stab_tolerance: float = 0.1
        self._stab_window_s: float = 120.0
        self._cooldown_threshold: float = -0.1
        self._warmup_threshold: float = 0.1
        self._room_temp_K: float = 280.0
        self._rate_window_s: float = 120.0
        self._pump_rate_threshold: float = -0.01

        self._temp_buf: deque[tuple[float, float]] = deque(maxlen=2000)
        self._pres_buf: deque[tuple[float, float]] = deque(maxlen=2000)

        self._stable_since: float | None = None
        self._last_phase: str = "unknown"
        self._warmup_started: bool = False

    def reset(self) -> None:
        """Reset all state. Call between experiments or from configure()."""
        self._temp_buf.clear()
        self._pres_buf.clear()
        self._stable_since = None
        self._last_phase = "unknown"
        self._warmup_started = False

    def configure(self, config: dict[str, Any]) -> None:
        self.reset()
        self._config = config
        self._temp_channel = config.get("temperature_channel", "")
        self._pressure_channel = config.get("pressure_channel", "")
        self._target_T = float(config.get("target_T_K", 4.2))
        self._stab_tolerance = float(config.get("stabilization_tolerance_K", 0.1))
        self._stab_window_s = float(config.get("stabilization_window_s", 120.0))
        self._cooldown_threshold = float(config.get("cooldown_rate_threshold", -0.1))
        self._warmup_threshold = float(config.get("warmup_rate_threshold", 0.1))
        self._room_temp_K = float(config.get("room_temp_K", 280.0))
        self._rate_window_s = float(config.get("rate_window_s", 120.0))
        self._pump_rate_threshold = float(config.get("pump_rate_threshold", -0.01))
        _log.info(
            "PhaseDetector configured: temp=%s, pressure=%s, target=%.1f K",
            self._temp_channel, self._pressure_channel, self._target_T,
        )

    async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
        if not self._temp_channel:
            return []

        for r in readings:
            if r.status != ChannelStatus.OK:
                continue
            if r.channel == self._temp_channel:
                self._temp_buf.append((r.timestamp.timestamp(), r.value))
            elif self._pressure_channel and r.channel == self._pressure_channel:
                if r.value > 0:
                    self._pres_buf.append((r.timestamp.timestamp(), math.log10(r.value)))

        if len(self._temp_buf) < 10:
            return []

        # Trim old data
        now = self._temp_buf[-1][0]
        cutoff = now - self._rate_window_s * 2
        while self._temp_buf and self._temp_buf[0][0] < cutoff:
            self._temp_buf.popleft()
        while self._pres_buf and self._pres_buf[0][0] < cutoff:
            self._pres_buf.popleft()

        dT_dt = self._compute_rate(self._temp_buf)
        current_T = self._temp_buf[-1][1]
        dlogP_dt = self._compute_rate(self._pres_buf) if len(self._pres_buf) >= 10 else None

        stable_duration = self._track_stability(current_T, now)
        phase, confidence = self._classify(current_T, dT_dt, dlogP_dt, stable_duration)
        self._last_phase = phase

        return [
            DerivedMetric.now(
                self.plugin_id, "detected_phase", _PHASE_CODES.get(phase, 0.0), "phase",
                metadata={"phase_name": phase, "confidence": confidence},
            ),
            DerivedMetric.now(
                self.plugin_id, "dT_dt_K_per_min", dT_dt, "K/min",
            ),
            DerivedMetric.now(
                self.plugin_id, "phase_confidence", confidence, "",
            ),
            DerivedMetric.now(
                self.plugin_id, "stable_at_target_s", stable_duration, "s",
            ),
        ]

    def _compute_rate(self, buf: deque[tuple[float, float]]) -> float:
        """OLS-style rate from window: value/minute."""
        if len(buf) < 5:
            return 0.0
        now = buf[-1][0]
        cutoff = now - self._rate_window_s
        points = [(t, v) for t, v in buf if t >= cutoff]
        if len(points) < 5:
            return 0.0
        t0 = points[0][0]
        n = len(points)
        sum_x = sum_y = sum_xy = sum_xx = 0.0
        for t, v in points:
            x = (t - t0) / 60.0
            sum_x += x
            sum_y += v
            sum_xy += x * v
            sum_xx += x * x
        denom = n * sum_xx - sum_x * sum_x
        if abs(denom) < 1e-12:
            return 0.0
        return (n * sum_xy - sum_x * sum_y) / denom

    def _track_stability(self, current_T: float, now: float) -> float:
        if abs(current_T - self._target_T) <= self._stab_tolerance:
            if self._stable_since is None:
                self._stable_since = now
            return now - self._stable_since
        else:
            self._stable_since = None
            return 0.0

    def _classify(
        self,
        T: float,
        dT_dt: float,
        dlogP_dt: float | None,
        stable_s: float,
    ) -> tuple[str, float]:
        # Measurement: stable at target
        if stable_s >= self._stab_window_s:
            return "measurement", min(1.0, stable_s / (self._stab_window_s * 2))

        # Near target
        if abs(T - self._target_T) <= self._stab_tolerance * 3:
            if dT_dt > self._warmup_threshold:
                self._warmup_started = True
                return "warmup", 0.7
            conf = 0.3 + 0.4 * (stable_s / self._stab_window_s) if stable_s > 0 else 0.3
            return "measurement", conf

        # Room temperature zone
        if T >= self._room_temp_K:
            if self._warmup_started or self._last_phase == "warmup":
                return "teardown", 0.8
            if dlogP_dt is not None and dlogP_dt < self._pump_rate_threshold:
                return "vacuum", 0.7
            return "preparation", 0.6

        # Below room temp, above target
        if dT_dt < self._cooldown_threshold:
            self._warmup_started = False
            return "cooldown", min(1.0, abs(dT_dt / self._cooldown_threshold) * 0.5)

        if dT_dt > self._warmup_threshold:
            self._warmup_started = True
            return "warmup", min(1.0, abs(dT_dt / self._warmup_threshold) * 0.5)

        # Slow transition — infer from context
        if self._last_phase == "cooldown" and T > self._target_T * 2:
            return "cooldown", 0.4
        if self._last_phase == "warmup":
            return "warmup", 0.4

        return "unknown", 0.1
