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
  contract (:meth:`set_cooldown`, :meth:`set_r_thermal`) plus new
  III.C setters (:meth:`set_temperature_readings`,
  :meth:`set_pressure_reading`, :meth:`set_keithley_readings`,
  :meth:`set_instrument_health`, :meth:`set_vacuum_prediction`).
- Each setter iterates the active widget instances and forwards to
  those that expose a matching method (duck-typing). Inactive
  widgets are discarded when the layout swaps.

Public API preserved for existing wiring tests; new setters additive.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from cryodaq.core.gas_inventory_format import MAX_FUTURE_SKEW_S
from cryodaq.core.reading_freshness import PREDICTION_STALE_AFTER_S
from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.views import analytics_widgets

logger = logging.getLogger(__name__)

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


# One owner for this boundary, in cryodaq.core.reading_freshness. The compact
# dashboard header renders the same ETA and used to keep its own copy of the
# number; two copies of one rule are two rules waiting to disagree.
_PREDICTION_STALE_AFTER_S = PREDICTION_STALE_AFTER_S


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

    # Provenance. Without these the widget cannot tell three different things
    # apart, and showed all of them as one confident number:
    #
    #   * before a cooldown is detected the predictor emits the ensemble prior —
    #     19.3 h, progress 0.0%, unchanging. That is a model reference, NOT an
    #     ETA derived from this run, and it sat on screen for five hours on
    #     2026-09-03 looking exactly like a live forecast;
    #   * during an active cooldown it is a genuine slope-adjusted forecast;
    #   * if the predictor is shed under load or fails, the last value simply
    #     stops updating, and nothing said so.
    #
    # `cooldown_active` was already in the published metadata and was being
    # discarded by the adapter. `generated_at` is the reading's own timestamp,
    # so staleness is judged against when the prediction was made rather than
    # when it happened to be rendered.
    cooldown_active: bool = False
    generated_at: float | None = None

    def freshness(self, *, now_epoch: float | None = None):
        """Judge this prediction against the shared freshness boundary."""

        import time as _time

        from cryodaq.core.reading_freshness import judge_freshness

        return judge_freshness(
            self.generated_at,
            now_epoch=_time.time() if now_epoch is None else now_epoch,
            max_age_s=_PREDICTION_STALE_AFTER_S,
        )

    def status_label(self, *, now_epoch: float | None = None) -> str:
        """One operator-facing description of what this number actually is."""

        verdict = self.freshness(now_epoch=now_epoch)
        if not verdict.is_current:
            return f"прогноз недоступен ({verdict.reason})"
        if not self.cooldown_active:
            return "базовая оценка по модели (охлаждение не обнаружено)"
        return "прогноз по наблюдаемой скорости"


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
        self._layout_applied: bool = False
        self._layout_config = _load_layout_config()
        self._active: dict[str, QWidget] = {}

        # Cached last pushes — replayed into new widgets on phase swap
        # so a fresh layout reflects the current state immediately.
        self._last_cooldown: CooldownData | None = None
        self._last_r_thermal: RThermalData | None = None
        self._last_gas_inventory = None
        # Captured ONCE, when a reading is admitted. Deliberately separate
        # from the retained reading: the reading may be dropped as
        # unreplayable while this still guards against older replays.
        self._last_gas_ordering_epoch: float | None = None
        self._last_temperature_readings: dict[str, Reading] = {}
        self._last_pressure_reading: Reading | None = None
        self._last_keithley_readings: dict[str, Reading] = {}
        self._last_instrument_health: dict[str, str] | None = None
        self._last_vacuum_prediction: dict | None = None
        self._last_experiment_status: dict | None = None
        # F-MockPredictor: cold-stage live reading routed via
        # set_cold_temperature_reading; replayed on phase swap.
        self._last_cold_temperature_reading: Reading | None = None
        self._cold_stage_unavailable_reason: str | None = None

        # Per-(setter_name, phase) set: suppresses repeat WARNINGs for the
        # same silent-skip within one phase so 33 Hz data streams don't flood
        # the log. Cleared on every phase transition via _apply_layout.
        self._warned_setters: set[tuple[str, str | None]] = set()

        # Outer column: a persistent cooldown-baseline verdict badge on top
        # (Task 8b — hidden when the feature is disabled or no baseline set),
        # then the phase-aware grid. The grid lives on an inner container so
        # `_place_in_slot` / `active_widgets` keep their existing semantics.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        outer.setSpacing(theme.SPACE_2)

        from cryodaq.gui.shell.overlays.cooldown_baseline_card import CooldownVerdictBadge

        self._verdict_badge = CooldownVerdictBadge()
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(theme.SPACE_2)
        badge_row.addStretch()
        badge_row.addWidget(self._verdict_badge)
        outer.addLayout(badge_row)

        grid_host = QWidget()
        outer.addWidget(grid_host, stretch=1)
        self._grid = QGridLayout(grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(theme.SPACE_3)
        # Layout is intentionally NOT applied here. _ensure_overlay in
        # MainWindowV2 calls set_phase() exactly once after construction,
        # which applies the layout in the correct final slot. Eager layout
        # in __init__ would construct fallback widgets that get immediately
        # destroyed when set_phase swaps to the active phase — killing any
        # in-flight ZmqCommandWorker QThreads parented to those widgets.

    # ------------------------------------------------------------------
    # Public API — phase
    # ------------------------------------------------------------------

    def set_phase(self, phase: str | None) -> None:
        # First call always applies layout (even when phase is None →
        # fallback). Subsequent identical-phase calls early-return as before.
        if self._layout_applied and phase == self._phase:
            return
        self._phase = phase
        self._layout_applied = True
        key = _resolve_phase_key(phase, self._layout_config)
        self._apply_layout(key)
        # Re-read the on-disk fingerprint/baseline state (cheap, phase-rate).
        self._verdict_badge.refresh()

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

    @staticmethod
    def _reading_epoch(reading) -> float | None:
        """Source time of a reading, or None when it cannot be established."""

        try:
            ts = float(reading.timestamp.timestamp())
        except (TypeError, ValueError, OSError, AttributeError):
            return None
        return ts if math.isfinite(ts) else None

    @classmethod
    def _ordering_epoch(cls, reading) -> float | None:
        """Source time usable as an ORDERING ANCHOR, or None.

        A future-dated reading is finite and parses perfectly, so it made a
        valid-looking anchor — and then nothing could ever beat it. One sample
        stamped `now + 360 s` became the cache, every genuine reading afterwards
        compared older and was discarded, and the cache stayed pinned to a value
        the consumers were simultaneously refusing to display. The readout was
        blank and unrecoverable, with a poisoned cache re-serving the bad value
        at every remount.

        The same skew boundary the consumers use decides this. A reading beyond
        it is FORWARDED to the consumers, which know how to refuse it, and then
        retained as nothing — see `set_gas_inventory`. It never anchors
        ordering, because recovery has to stay possible, and it is never kept
        for replay, because a reading that cannot be placed in time must not be
        handed to a freshly mounted card.
        """

        ts = cls._reading_epoch(reading)
        if ts is None:
            return None
        return None if ts > time.time() + MAX_FUTURE_SKEW_S else ts

    def set_gas_inventory(self, reading) -> None:
        """Latest molecular-counter reading. Retained for replay on phase swap.

        The cache is ordered by SOURCE TIME, not by arrival. It is replayed into
        a freshly mounted card on every phase or layout swap, so a stale replay
        that overwrote it would keep displacing the live value long after the
        replay itself was forgotten — the widgets would each be correct while
        the thing that re-feeds them held a superseded reading.

        Fixing the two visible consumers is therefore not enough on its own:
        they would reject the stale reading, and then be handed it again by this
        cache at the next remount.
        """

        incoming = self._ordering_epoch(reading)

        if incoming is None:
            # Undateable, or dated too far ahead to be believed. That verdict is
            # DURABLE: it was reached against the clock at admission and is
            # never revisited.
            #
            # Recomputing it from the retained object was a time-of-check /
            # time-of-use defect. A reading 360 s in the future is refused under
            # a 300 s bound — and then, sixty-one seconds later, the very same
            # object is only 299 s ahead and silently becomes admissible. It
            # would anchor ordering, discard genuine current readings, and be
            # replayed into a freshly mounted card as though it were live.
            # Validity cannot improve merely because time passed.
            #
            # So: tell the consumers, which know how to fail closed; keep
            # nothing replayable; and leave the last valid ordering position
            # alone, so protection against older replays survives and a remount
            # stays unavailable until something genuinely valid arrives.
            self._last_gas_inventory = None
            self._forward("set_gas_inventory", reading)
            return

        held = self._last_gas_ordering_epoch
        if held is not None and incoming <= held:
            # Superseded: neither cached nor forwarded. Both consumers would
            # reject it anyway; forwarding it would only rely on that.
            return

        self._last_gas_ordering_epoch = incoming
        self._last_gas_inventory = reading
        self._forward("set_gas_inventory", reading)

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

    def set_experiment_status(self, status: dict | None) -> None:
        self._last_experiment_status = status
        self._forward("set_experiment_status", status)

    def set_cold_temperature_reading(self, reading: Reading) -> None:
        """F-MockPredictor: forward a cold-stage temperature reading to widgets
        that own a SteadyStatePredictor for stationarity detection."""
        self._last_cold_temperature_reading = reading
        self._forward("set_cold_temperature_reading", reading)

    def set_cold_stage_unavailable(self, reason: str) -> None:
        """Render the exact absence of a cold-stage policy declaration."""
        self._cold_stage_unavailable_reason = reason
        self._forward_to(list(self._active.values()), "set_cold_stage_unavailable", reason)

    def clear_cold_stage_unavailable(self) -> None:
        """Restore the declared cold-stage widget to its live-data state."""
        self._cold_stage_unavailable_reason = None
        self._forward_to(list(self._active.values()), "clear_cold_stage_unavailable")

    # ------------------------------------------------------------------
    # Layout management
    # ------------------------------------------------------------------

    def active_widgets(self) -> dict[str, QWidget]:
        """Snapshot of current slot → widget mapping (for tests)."""
        return dict(self._active)

    def _apply_layout(self, phase_key: str) -> None:
        # New phase → new widget set → prior silent-skip warnings are stale.
        self._warned_setters.clear()
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
        """Call ``method(*args)`` on every active widget that defines it.

        Logs a WARNING when no active widget implements the setter — data is
        being silently dropped. Guard: only warns when there *are* active
        widgets, so the warning is not emitted during empty-layout transitions.
        """
        forwarded = False
        for widget in self._active.values():
            fn = getattr(widget, method, None)
            if callable(fn):
                fn(*args)
                forwarded = True
        if not forwarded and self._active:
            key = (method, self._phase)
            if key not in self._warned_setters:
                self._warned_setters.add(key)
                logger.warning(
                    "%s: no active widget in phase=%r implements setter; data dropped. Active widgets: %s",
                    method,
                    self._phase,
                    [type(w).__name__ for w in self._active.values()],
                )

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
        :class:`PressureCurrentWidget`. Phase III.C fix.
        """
        if not widgets:
            return
        if self._last_cooldown is not None:
            self._forward_to(widgets, "set_cooldown_data", self._last_cooldown)
        # Independent of cooldown data: the gas card is mounted in `vacuum` too,
        # where there is no cooldown at all. Nested under that guard it would
        # never replay in the phase it was added for.
        if self._last_gas_inventory is not None:
            self._forward_to(widgets, "set_gas_inventory", self._last_gas_inventory)
        if self._last_r_thermal is not None:
            self._forward_to(widgets, "set_r_thermal_data", self._last_r_thermal)
        if self._last_temperature_readings:
            self._forward_to(widgets, "set_temperature_readings", self._last_temperature_readings)
        if self._last_pressure_reading is not None:
            self._forward_to(widgets, "set_pressure_reading", self._last_pressure_reading)
        if self._last_keithley_readings:
            self._forward_to(widgets, "set_keithley_readings", self._last_keithley_readings)
        if self._last_instrument_health is not None:
            self._forward_to(widgets, "set_instrument_health", self._last_instrument_health)
        if self._last_vacuum_prediction is not None:
            self._forward_to(widgets, "set_vacuum_prediction", self._last_vacuum_prediction)
        if self._last_experiment_status is not None:
            self._forward_to(widgets, "set_experiment_status", self._last_experiment_status)
        if self._last_cold_temperature_reading is not None:
            self._forward_to(
                widgets,
                "set_cold_temperature_reading",
                self._last_cold_temperature_reading,
            )
        if self._cold_stage_unavailable_reason is not None:
            self._forward_to(
                widgets,
                "set_cold_stage_unavailable",
                self._cold_stage_unavailable_reason,
            )
        else:
            self._forward_to(widgets, "clear_cold_stage_unavailable")
