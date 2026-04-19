"""Analytics primary view — phase-aware dynamic layout (Phase III.C).

Consumes ``config/analytics_layout.yaml`` to decide which widget goes
in the 1/2-screen main slot + top-right 1/4 + bottom-right 1/4 per
experiment phase. Layout swaps when :meth:`set_phase` is called by the
shell.

Connects to:
- :class:`GlobalTimeWindowController` (indirectly via embedded
  historical widgets; AnalyticsView itself holds no TimeWindow state).
- Experiment phase string forwarded from
  :class:`MainWindowV2._on_experiment_status_received` via
  :meth:`set_phase`.

Data flow:
- Shell routes data via setter methods preserved from the B.8
  contract (:meth:`set_cooldown`, :meth:`set_r_thermal`,
  :meth:`set_fault`) plus new III.C setters
  (:meth:`set_temperature_readings`, :meth:`set_pressure_reading`,
  :meth:`set_keithley_readings`, :meth:`set_instrument_health`,
  :meth:`set_vacuum_prediction`).
- Each setter iterates the active widget instances and forwards to
  those that expose a matching method (duck-typing). Inactive
  widgets are discarded when the layout swaps.

Public API preserved for existing wiring tests; new setters additive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.views import analytics_widgets

_LAYOUT_CONFIG_PATH = Path(__file__).resolve().parents[5] / "config" / "analytics_layout.yaml"
_FALLBACK_KEY = "__fallback__"

# Phase label aliases — forward compatibility between
# `core.phase_labels.PHASE_ORDER` string IDs and YAML keys.
_PHASE_ALIASES: dict[str, str] = {
    # Engine/ExperimentPhase.value → YAML phase key
    "preparation": "preparation",
    "vacuum": "vacuum",
    "cooldown": "cooldown",
    "measurement": "measurement",
    "warmup": "warmup",
    "teardown": "disassembly",
    "disassembly": "disassembly",
}


# ─── Data contracts preserved from B.8 ────────────────────────────────


@dataclass
class CooldownData:
    """Snapshot of cooldown predictor output.

    Pushed by ``MainWindowV2._cooldown_reading_to_data`` from the
    ``analytics/cooldown_predictor/cooldown_eta`` broker channel.
    Field set preserved for wiring compatibility.
    """

    t_hours: float
    ci_hours: float
    phase: str
    progress_pct: float
    actual_trajectory: list[tuple[float, float]] = field(default_factory=list)
    predicted_trajectory: list[tuple[float, float]] = field(default_factory=list)
    ci_trajectory: list[tuple[float, float, float]] = field(default_factory=list)
    phase_boundaries_hours: list[float] = field(default_factory=list)


@dataclass
class RThermalData:
    """Thermal resistance snapshot. Pushed when a downstream plugin
    eventually emits R_thermal data."""

    current_value: float | None
    delta_per_minute: float | None
    last_updated_ts: float
    history: list[tuple[float, float]] = field(default_factory=list)


# ─── Layout config loader ─────────────────────────────────────────────


def _load_layout_config() -> dict:
    if not _LAYOUT_CONFIG_PATH.exists():
        return {"phases": {}, "fallback": {"main": None, "top_right": None, "bottom_right": None}}
    with _LAYOUT_CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {"phases": {}, "fallback": {}}


def _resolve_phase_key(phase: str | None, config: dict) -> str:
    """Map a phase string (engine ID or alias) onto a YAML key."""
    if phase is None:
        return _FALLBACK_KEY
    alias = _PHASE_ALIASES.get(phase, phase)
    phases = config.get("phases") or {}
    return alias if alias in phases else _FALLBACK_KEY


def _slots_for(phase_key: str, config: dict) -> dict[str, str | None]:
    phases = config.get("phases") or {}
    if phase_key == _FALLBACK_KEY or phase_key not in phases:
        cfg = config.get("fallback") or {}
    else:
        cfg = phases[phase_key]
    return {
        "main": cfg.get("main"),
        "top_right": cfg.get("top_right"),
        "bottom_right": cfg.get("bottom_right"),
    }


# ─── View ─────────────────────────────────────────────────────────────


class AnalyticsView(QWidget):
    """Phase-aware primary analytics view (Phase III.C)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analyticsView")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#analyticsView {{ background-color: {theme.BACKGROUND}; }}")

        self._phase: str | None = None
        self._layout_config = _load_layout_config()
        self._active: dict[str, QWidget] = {}

        # Cached last pushes — replayed into new widgets on phase swap
        # so a fresh layout reflects the current state immediately.
        self._last_cooldown: CooldownData | None = None
        self._last_r_thermal: RThermalData | None = None
        # None sentinel = set_fault never called. Empty-default tuple
        # would otherwise skip replay after an explicit `set_fault(False, "")`
        # clear, which III.C Codex flagged as a latent replay-contract hole.
        self._last_fault: tuple[bool, str] | None = None
        self._last_temperature_readings: dict[str, Reading] = {}
        self._last_pressure_reading: Reading | None = None
        self._last_keithley_readings: dict[str, Reading] = {}
        self._last_instrument_health: dict[str, str] | None = None
        self._last_vacuum_prediction: dict | None = None

        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        self._grid.setSpacing(theme.SPACE_3)

        self._apply_layout(_FALLBACK_KEY)

    # ------------------------------------------------------------------
    # Public API — phase
    # ------------------------------------------------------------------

    def set_phase(self, phase: str | None) -> None:
        if phase == self._phase:
            return
        self._phase = phase
        key = _resolve_phase_key(phase, self._layout_config)
        self._apply_layout(key)

    def current_phase(self) -> str | None:
        return self._phase

    # ------------------------------------------------------------------
    # Public API — data setters (forward to active widgets via duck-typing)
    # ------------------------------------------------------------------

    def set_cooldown(self, data: CooldownData | None) -> None:
        self._last_cooldown = data
        self._forward("set_cooldown_data", data)

    def set_r_thermal(self, data: RThermalData | None) -> None:
        self._last_r_thermal = data
        self._forward("set_r_thermal_data", data)

    def set_fault(self, faulted: bool, reason: str = "") -> None:
        self._last_fault = (faulted, reason)
        self._forward("set_fault", faulted, reason)

    def set_temperature_readings(self, readings: dict[str, Reading]) -> None:
        # Keep the latest value per channel for replay on layout swap.
        self._last_temperature_readings.update(readings)
        self._forward("set_temperature_readings", readings)

    def set_pressure_reading(self, reading: Reading) -> None:
        self._last_pressure_reading = reading
        self._forward("set_pressure_reading", reading)

    def set_keithley_readings(self, readings: dict[str, Reading]) -> None:
        self._last_keithley_readings.update(readings)
        self._forward("set_keithley_readings", readings)

    def set_instrument_health(self, health: dict[str, str] | None) -> None:
        self._last_instrument_health = health
        self._forward("set_instrument_health", health)

    def set_vacuum_prediction(self, prediction: dict | None) -> None:
        self._last_vacuum_prediction = prediction
        self._forward("set_vacuum_prediction", prediction)

    # ------------------------------------------------------------------
    # Layout management
    # ------------------------------------------------------------------

    def active_widgets(self) -> dict[str, QWidget]:
        """Snapshot of current slot → widget mapping (for tests)."""
        return dict(self._active)

    def _apply_layout(self, phase_key: str) -> None:
        new_slots = _slots_for(phase_key, self._layout_config)

        # Drop widgets whose slot now wants a different ID (or is empty).
        for slot, widget in list(self._active.items()):
            desired_id = new_slots.get(slot)
            if analytics_widgets.id_of(widget) != desired_id:
                self._grid.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()
                del self._active[slot]

        # Instantiate missing widgets — track which ones are fresh so
        # the replay step below only targets them (replaying into a
        # preserved append-style widget would duplicate samples).
        fresh: list[QWidget] = []
        for slot, widget_id in new_slots.items():
            if slot in self._active:
                continue
            if widget_id is None:
                continue
            widget = analytics_widgets.create(widget_id)
            if widget is None:
                continue
            self._active[slot] = widget
            self._place_in_slot(slot, widget)
            fresh.append(widget)

        # Column / row stretch — two-column layout, main slot takes
        # the full left column (both rows), right column 1/3 width.
        self._grid.setColumnStretch(0, 2)
        self._grid.setColumnStretch(1, 1)
        self._grid.setRowStretch(0, 1)
        self._grid.setRowStretch(1, 1)

        # Replay cached pushes into the freshly-mounted widgets only.
        self._replay_cached_into(fresh)

    def _place_in_slot(self, slot: str, widget: QWidget) -> None:
        if slot == "main":
            # row=0, col=0, rowspan=2, colspan=1
            self._grid.addWidget(widget, 0, 0, 2, 1)
        elif slot == "top_right":
            self._grid.addWidget(widget, 0, 1, 1, 1)
        elif slot == "bottom_right":
            self._grid.addWidget(widget, 1, 1, 1, 1)

    def _forward(self, method: str, *args) -> None:
        """Call ``method(*args)`` on every active widget that defines it."""
        for widget in self._active.values():
            fn = getattr(widget, method, None)
            if callable(fn):
                fn(*args)

    @staticmethod
    def _forward_to(widgets: list[QWidget], method: str, *args) -> None:
        for widget in widgets:
            fn = getattr(widget, method, None)
            if callable(fn):
                fn(*args)

    def _replay_cached_into(self, widgets: list[QWidget]) -> None:
        """Push the last known data into freshly-mounted widgets only.

        Replaying into preserved (already-active-in-prior-layout)
        widgets would duplicate samples in append-style consumers like
        :class:`TemperatureOverviewWidget` and
        :class:`PressureCurrentWidget`. Phase III.C Codex fix.
        """
        if not widgets:
            return
        if self._last_cooldown is not None:
            self._forward_to(widgets, "set_cooldown_data", self._last_cooldown)
        if self._last_r_thermal is not None:
            self._forward_to(widgets, "set_r_thermal_data", self._last_r_thermal)
        if self._last_fault is not None:
            self._forward_to(widgets, "set_fault", *self._last_fault)
        if self._last_temperature_readings:
            self._forward_to(
                widgets, "set_temperature_readings", self._last_temperature_readings
            )
        if self._last_pressure_reading is not None:
            self._forward_to(widgets, "set_pressure_reading", self._last_pressure_reading)
        if self._last_keithley_readings:
            self._forward_to(
                widgets, "set_keithley_readings", self._last_keithley_readings
            )
        if self._last_instrument_health is not None:
            self._forward_to(
                widgets, "set_instrument_health", self._last_instrument_health
            )
        if self._last_vacuum_prediction is not None:
            self._forward_to(
                widgets, "set_vacuum_prediction", self._last_vacuum_prediction
            )
