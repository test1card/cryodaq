"""Small coupled thermal-sample model for mock instrument drivers."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable


class ThermalSampleSimulator:
    """Evolve one sample temperature difference from measured heater power."""

    def __init__(
        self,
        *,
        bath_temperature_k: float = 4.2,
        thermal_resistance_k_per_w: float = 8.0,
        time_constant_s: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        for name, value in (
            ("bath_temperature_k", bath_temperature_k),
            ("thermal_resistance_k_per_w", thermal_resistance_k_per_w),
            ("time_constant_s", time_constant_s),
        ):
            if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0.0:
                raise ValueError(f"{name} must be a finite positive number")
        self._bath_temperature_k = float(bath_temperature_k)
        self._thermal_resistance_k_per_w = float(thermal_resistance_k_per_w)
        self._time_constant_s = float(time_constant_s)
        self._clock = clock
        self._power_w = 0.0
        self._temperature_rise_k = 0.0
        self._last_update_s = float(clock())
        self._lock = threading.Lock()

    def _advance_locked(self) -> None:
        now = float(self._clock())
        if not math.isfinite(now):
            raise ValueError("thermal simulator clock must return a finite value")
        if now <= self._last_update_s:
            return
        elapsed_s = now - self._last_update_s
        equilibrium_rise_k = self._power_w * self._thermal_resistance_k_per_w
        decay = math.exp(-elapsed_s / self._time_constant_s)
        self._temperature_rise_k = equilibrium_rise_k + (self._temperature_rise_k - equilibrium_rise_k) * decay
        self._last_update_s = now

    def set_power(self, power_w: float) -> None:
        """Advance with the old power, then apply a new non-negative power."""

        if isinstance(power_w, bool) or not math.isfinite(float(power_w)) or float(power_w) < 0.0:
            raise ValueError("power_w must be a finite non-negative number")
        with self._lock:
            self._advance_locked()
            self._power_w = float(power_w)

    @property
    def power_w(self) -> float:
        with self._lock:
            return self._power_w

    def temperature_pair(self) -> tuple[float, float]:
        """Return the hot-side and cold-side temperatures in kelvin."""

        with self._lock:
            self._advance_locked()
            cold_k = self._bath_temperature_k
            return cold_k + self._temperature_rise_k, cold_k
