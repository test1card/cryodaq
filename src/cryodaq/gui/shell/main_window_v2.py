"""MainWindowV2 — Phase UI-1 v2 shell host.

Replaces the tab-based MainWindow. Layout:

    ┌──────────────────────────────────────────┐
    │ TopWatchBar                              │
    ├────┬─────────────────────────────────────┤
    │ TR │ OverlayContainer (dashboard/overlay)│
    ├────┴─────────────────────────────────────┤
    │ BottomStatusBar                          │
    └──────────────────────────────────────────┘

Constructor signature matches the old MainWindow so the launcher and
gui/app.py can swap implementations without further changes.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from PySide6.QtCore import QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.core.channel_manager import get_channel_manager
from cryodaq.core.descriptor_transport import DescriptorQualifiedReading
from cryodaq.drivers.base import Reading
from cryodaq.gui.dashboard import DashboardView
from cryodaq.gui.shell.annunciation_controller import AnnunciationController
from cryodaq.gui.shell.bottom_status_bar import BottomStatusBar
from cryodaq.gui.shell.experiment_overlay import ExperimentOverlay
from cryodaq.gui.shell.new_experiment_dialog import NewExperimentDialog
from cryodaq.gui.shell.overlay_container import OverlayContainer
from cryodaq.gui.shell.overlays.alarm_panel import AlarmPanel
from cryodaq.gui.shell.overlays.archive_panel import ArchivePanel
from cryodaq.gui.shell.overlays.calibration_panel import CalibrationPanel
from cryodaq.gui.shell.overlays.conductivity_panel import ConductivityPanel
from cryodaq.gui.shell.overlays.instruments_panel import InstrumentsPanel
from cryodaq.gui.shell.overlays.keithley_panel import KeithleyPanel
from cryodaq.gui.shell.overlays.knowledge_base_panel import KnowledgeBasePanel
from cryodaq.gui.shell.overlays.multiline_panel import MultiLinePanel, is_manifest_multiline_descriptor
from cryodaq.gui.shell.overlays.operator_log_panel import OperatorLogPanel
from cryodaq.gui.shell.tool_rail import ToolRail
from cryodaq.gui.shell.top_watch_bar import TopWatchBar
from cryodaq.gui.shell.views.analytics_view import AnalyticsView
from cryodaq.gui.shell.views.operator_display import OperatorDisplay
from cryodaq.gui.state.descriptor_store import (
    DescriptorStore,
    DescriptorView,
    IdentityStatus,
    IngestResult,
)
from cryodaq.gui.zmq_client import ZmqBridge
from cryodaq.operator_snapshot import (
    OperatorPresentationState,
    OperatorSnapshot,
    ReadinessTruth,
    SafetyLifecycle,
    SnapshotMode,
)

logger = logging.getLogger(__name__)

_SAFETY_READY_STATES = frozenset({"ready", "run_permitted", "running"})
_SAFETY_REASON_MAX_CHARS = 120
_DISK_FUTURE_TOLERANCE_S = 5.0
_DISK_MAX_SOURCE_AGE_S = 600.0
_SAFETY_FUTURE_TOLERANCE_S = 5.0
_SAFETY_MAX_SOURCE_AGE_S = 10.0
_WORKER_SETTLE_MS = 1_500


def _is_manifest_cold_stage_descriptor(descriptor: ChannelDescriptorV1) -> bool:
    return (
        descriptor.channel_id == "Т12"
        and descriptor.instrument_id == "LS218_2"
        and descriptor.source_key == "input.4.temperature"
        and descriptor.quantity is ChannelQuantity.TEMPERATURE
        and descriptor.unit == "K"
        and descriptor.role is ChannelRole.PRIMARY_MEASUREMENT
        and descriptor.safety_class is ChannelSafetyClass.SAFETY_CRITICAL_INPUT
        and descriptor.display_group == "компрессор"
    )


def _map_safety_state(state: str | None, reason: str) -> tuple[bool, str]:
    """Translate engine safety state + reason into the Keithley overlay's
    (ready, reason_text) gate input. Pure function; testable in isolation.

    - Ready states (``ready`` / ``run_permitted`` / ``running``) return
      ``(True, "")`` — normal control allowed.
    - Blocked states return ``(False, reason_or_state_name)``. The engine's
      free-form reason text (e.g. ``"Interlock 'vacuum_lost' tripped: ..."``)
      is preferred; falls back to the state name when no reason is published.
    """

    if state in _SAFETY_READY_STATES:
        return True, ""
    fallback = state if state else "unknown"
    text = reason.strip()
    if not text:
        text = fallback
    if len(text) > _SAFETY_REASON_MAX_CHARS:
        logger.warning(
            "Safety reason truncated from %d to %d chars: %s",
            len(text),
            _SAFETY_REASON_MAX_CHARS,
            text[:_SAFETY_REASON_MAX_CHARS],
        )
        text = text[:_SAFETY_REASON_MAX_CHARS] + "…"
    return False, text


class MainWindowV2(QMainWindow):
    """New shell-based main window for CryoDAQ."""

    _reading_received = Signal(object)

    def __init__(
        self,
        bridge: ZmqBridge | None = None,
        parent: QWidget | None = None,
        *,
        embedded: bool = False,
        subscriber: Any | None = None,
        replay_mode: bool = False,
    ) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._embedded = embedded
        self._replay_mode = bool(replay_mode)
        self._start_time = time.monotonic()
        self._reading_count = 0
        self._rate_count = 0
        self._last_rate_time = time.monotonic()
        self._last_reading_time = 0.0
        self._last_safety_state: str | None = None
        self._last_safety_reason: str = ""
        self._last_safety_observed_at: datetime | None = None
        self._accepted_safety_bridge_instance_id: str | None = None
        self._accepted_safety_experiment_id: str | None = None
        self._typed_safety_authority_seen = False
        self._typed_safety_producer_id: str | None = None
        self._typed_safety_revision: int | None = None
        self._typed_safety_ready = False
        self._last_disk_observed_at: datetime | None = None
        self._accepted_disk_bridge_instance_id: str | None = None

        self.setWindowTitle("CryoDAQ")
        self.setMinimumSize(1280, 800)

        self._channel_mgr = get_channel_manager()
        # D7.1b: descriptor identity store — GUI-thread-owned, lives for one session.
        self._descriptor_store = DescriptorStore()
        self._build_ui()
        self._reading_received.connect(self._dispatch_reading)

        # Status bar refresh: data rate, connection (1 Hz)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._tick_status)
        self._status_timer.start()

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    # Factories for lazy overlay construction. Panels are built on first
    # show_overlay() call. Eager construction would create every panel up
    # front (~10 panels with their own poll timers) which is wasteful and
    # leaks pending QTimer.singleShot callbacks across the test boundary.
    _OVERLAY_FACTORIES = {
        "experiment": ("_experiment_overlay", lambda self: ExperimentOverlay()),
        "source": ("_keithley_panel", lambda self: KeithleyPanel()),
        "analytics": ("_analytics_view", lambda self: AnalyticsView()),
        "conductivity": ("_conductivity_panel", lambda self: ConductivityPanel()),
        "multiline": ("_multiline_panel", lambda self: MultiLinePanel()),
        "knowledge_base": ("_knowledge_base_panel", lambda self: KnowledgeBasePanel()),
        "log": ("_operator_log_panel", lambda self: OperatorLogPanel()),
        "instruments": ("_instrument_panel", lambda self: InstrumentsPanel()),
        "archive": ("_archive_panel", lambda self: ArchivePanel()),
        "calibration": ("_calibration_panel", lambda self: CalibrationPanel()),
    }

    def _build_ui(self) -> None:
        # Eager: the comprehensive dashboard is the primary operator surface.
        # The one-cut shift briefing remains available as an additive summary.
        self._overview_panel = DashboardView(self._channel_mgr)
        self._overview_panel.setParent(self)
        self._overview_panel.set_read_only(self._replay_mode)
        self._overview_panel.set_connected(False)
        self._operator_display = OperatorDisplay()
        self._alarm_panel = AlarmPanel()
        self._alarm_panel.set_read_only(self._replay_mode)
        # Lazy panel slots — populated on first overlay open
        self._experiment_overlay: ExperimentOverlay | None = None
        self._keithley_panel: KeithleyPanel | None = None
        self._analytics_view: AnalyticsView | None = None
        self._conductivity_panel: ConductivityPanel | None = None
        self._multiline_panel: MultiLinePanel | None = None
        self._knowledge_base_panel: KnowledgeBasePanel | None = None

        # F4 lazy-open snapshot replay cache (F3-Cycle1).
        # Last-value setters: dict[setter_name → last args tuple].
        # Accumulating setters: separate dicts keyed by full channel name.
        # set_fault is intentionally excluded from replay (spec §4.5).
        self._analytics_snapshot: dict[str, tuple] = {}
        self._analytics_temperature_snapshot: dict[str, Reading] = {}
        self._analytics_keithley_snapshot: dict[str, Reading] = {}
        # v0.55.15 (audit SCOPE 5 finding 5.7) — MultiLine readings
        # cache. Accumulates the latest reading per channel so a panel
        # opened after readings start arriving still gets a populated
        # table on the very first refresh, instead of needing a fresh
        # cycle from the engine to populate.
        self._multiline_snapshot: dict[str, tuple[Reading, ChannelDescriptorV1]] = {}
        # Track active experiment ID to detect boundaries for cache invalidation.
        self._analytics_last_exp_id: str | None = None
        self._operator_log_panel: OperatorLogPanel | None = None
        self._instrument_panel: InstrumentsPanel | None = None
        self._archive_panel: ArchivePanel | None = None
        self._calibration_panel: CalibrationPanel | None = None

        # Shell components
        self._top_bar = TopWatchBar(channel_manager=self._channel_mgr)
        self._top_bar.set_replay_mode(self._replay_mode)
        self._tool_rail = ToolRail()
        self._bottom_bar = BottomStatusBar()
        # The only in-shell owner of engine annunciation sound.  Launcher
        # process-death sound remains deliberately separate.
        self._annunciation_controller = AnnunciationController(self)
        self._overlay = OverlayContainer()

        self._overlay.register("home", self._overview_panel)
        # F36: the supplemental briefing consumes only complete immutable
        # operator snapshots and remains navigation-only.
        self._overlay.register("summary", self._operator_display)
        # AlarmPanel needs a stack page but is not visible by default
        self._overlay.register("alarms", self._alarm_panel)
        self._overlay.show_dashboard()
        self._tool_rail.set_active("home")

        # Wire signals
        self._tool_rail.tool_clicked.connect(self._on_tool_clicked)
        self._operator_display.route_requested.connect(self._on_tool_clicked)
        self._top_bar.experiment_clicked.connect(self._on_experiment_clicked)
        self._top_bar.alarms_clicked.connect(lambda: self._on_tool_clicked("alarms"))

        # AlarmPanel is the sole validated snapshot/count owner.
        self._alarm_panel.v2_alarm_summary_changed.connect(self._top_bar.set_alarm_summary)
        self._alarm_panel.v2_alarm_availability_changed.connect(self._top_bar.set_alarm_available)

        # B.5: forward experiment status from top bar to dashboard phase widget
        self._top_bar.experiment_status_received.connect(self._on_experiment_status_received)
        self._latest_experiment_status: dict | None = None

        # B.8: wire dashboard «+ Создать» button to new experiment dialog
        if hasattr(self._overview_panel, "_phase_widget") and self._overview_panel._phase_widget is not None:
            self._overview_panel._phase_widget.create_experiment_requested.connect(self._show_new_experiment_dialog)

        # Compose layout
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._top_bar)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(self._tool_rail)
        middle.addWidget(self._overlay, stretch=1)
        root.addLayout(middle, stretch=1)

        root.addWidget(self._bottom_bar)
        self.setCentralWidget(central)

    # ------------------------------------------------------------------
    # Tool rail handler
    # ------------------------------------------------------------------

    @Slot(object)
    def render_operator_snapshot(self, snapshot: object) -> None:
        """Present one ingress-qualified cut through the POD transaction."""
        # Actuator gating is the fail-closed edge of the transaction. Revoke
        # it before any passive presentation sink is allowed to reject/raise.
        self._apply_operator_snapshot_safety(snapshot)
        self._operator_display.render(snapshot)
        self._overview_panel.set_operator_snapshot(snapshot)

    def _apply_operator_snapshot_safety(self, snapshot: object) -> None:
        """Use only exact, current POD readiness as Keithley gate authority."""
        # Once the typed POD path is present, legacy analytics remains
        # observational forever for this window. A malformed typed delivery
        # must fail closed, not silently reactivate the legacy fallback.
        self._typed_safety_authority_seen = True
        if type(snapshot) is not OperatorSnapshot:
            self._invalidate_safety_authority("Некорректный снимок состояния Safety")
            return
        cut = snapshot.cut
        readiness = snapshot.readiness
        bridge_instance_id = self._current_bridge_instance_id()
        producer_changed = self._typed_safety_producer_id not in (None, cut.producer_id)
        if producer_changed:
            self._typed_safety_revision = None
            self._typed_safety_ready = False
        if (
            self._typed_safety_revision is not None
            and cut.producer_id == self._typed_safety_producer_id
            and cut.revision < self._typed_safety_revision
        ):
            self._invalidate_safety_authority("Safety snapshot revision regressed")
            return
        ready = (
            bridge_instance_id is not None
            and cut.mode is SnapshotMode.LIVE
            and readiness.readiness is ReadinessTruth.READY
            and readiness.lifecycle is SafetyLifecycle.READY
            and readiness.status.state is OperatorPresentationState.OK
            and not readiness.status.transport_reason_codes
        )
        if (
            self._typed_safety_revision is not None
            and cut.producer_id == self._typed_safety_producer_id
            and cut.revision == self._typed_safety_revision
            and ready
            and not self._typed_safety_ready
        ):
            # A same-cut degraded state cannot recover authority. Only a newer
            # coherent Safety-owner cut can re-enable controls.
            return
        self._typed_safety_producer_id = cut.producer_id
        self._typed_safety_revision = cut.revision
        self._typed_safety_ready = ready
        self._accepted_safety_experiment_id = snapshot.experiment.experiment_id
        self._accepted_safety_bridge_instance_id = bridge_instance_id
        self._last_safety_state = readiness.lifecycle.value
        self._last_safety_reason = readiness.status.operator_text
        transport_stale = readiness.status.state in {
            OperatorPresentationState.STALE,
            OperatorPresentationState.DISCONNECTED,
        }
        self._bottom_bar.set_safety_state(self._last_safety_state, stale=transport_stale)
        if self._keithley_panel is not None:
            reason = "" if ready else "Состояние Safety устарело" if transport_stale else readiness.status.operator_text
            self._keithley_panel.set_safety_ready(ready, reason)

    @Slot(str)
    def _on_tool_clicked(self, name: str) -> None:
        if self._replay_mode and name in {
            "new_experiment",
            "restart_engine",
            "settings",
            "calibration",
        }:
            logger.warning("Replay mode rejected mutating shell route: %s", name)
            return
        if name == "new_experiment":
            self._show_new_experiment_dialog()
            return
        if name == "web_panel":
            self._open_web_panel()
            return
        if name == "restart_engine":
            self._restart_engine()
            return
        if name == "settings":
            # Stub: settings dialog comes later. Open existing channel editor.
            from cryodaq.gui.widgets.channel_editor import ChannelEditorDialog

            ChannelEditorDialog(self).exec()
            return
        if name == "home":
            self._overlay.show_dashboard()
            self._tool_rail.set_active("home")
            return
        # Lazy-construct overlay panel on first open
        self._ensure_overlay(name)
        self._overlay.show_overlay(name)
        self._tool_rail.set_active(name)

    def _ensure_overlay(self, name: str) -> None:
        """Build the overlay panel and register it on first access."""
        if name not in self._OVERLAY_FACTORIES:
            return
        attr, factory = self._OVERLAY_FACTORIES[name]
        if getattr(self, attr) is not None:
            return
        widget = factory(self)
        setattr(self, attr, widget)
        self._overlay.register(name, widget)
        if name in {"source", "experiment", "log", "multiline"}:
            widget.set_read_only(self._replay_mode)
        # II.6 post-review: replay cached connection + safety state into
        # the Keithley overlay on first construction. Without this the
        # overlay stays in its fail-closed default (disconnected, safety_ready=False)
        # until the next _tick_status / safety_state event arrives.
        if name == "source":
            derived_connected = False
            if self._last_reading_time > 0.0:
                derived_connected = (time.monotonic() - self._last_reading_time) < 3.0
            widget.set_connected(derived_connected)
            ready, reason_text = self._current_keithley_safety_gate()
            widget.set_safety_ready(ready, reason_text)
        # Phase II.3: replay connection + current experiment into OperatorLog
        # overlay on first construction (same contract pattern as II.6).
        if name == "log":
            derived_connected = False
            if self._last_reading_time > 0.0:
                derived_connected = (time.monotonic() - self._last_reading_time) < 3.0
            widget.set_connected(derived_connected)
            widget.set_current_experiment(self._active_experiment_id())
        # Phase II.2: replay connection state into Archive overlay.
        # Archive is global scope — no current_experiment push needed.
        if name == "archive":
            derived_connected = False
            if self._last_reading_time > 0.0:
                derived_connected = (time.monotonic() - self._last_reading_time) < 3.0
            widget.set_connected(derived_connected)
        # Phase II.5: replay connection state into Conductivity overlay.
        if name == "conductivity":
            derived_connected = False
            if self._last_reading_time > 0.0:
                derived_connected = (time.monotonic() - self._last_reading_time) < 3.0
            widget.set_connected(derived_connected)
        # v0.55.6: replay connection state into MultiLine overlay. Same
        # contract as the other measurement overlays.
        if name == "multiline":
            derived_connected = False
            if self._last_reading_time > 0.0:
                derived_connected = (time.monotonic() - self._last_reading_time) < 3.0
            widget.set_connected(derived_connected)
            # v0.55.15 (audit SCOPE 5 finding 5.7) — replay every
            # cached MultiLine reading so the panel's table populates
            # immediately rather than waiting for the next engine cycle.
            for reading, descriptor in self._multiline_snapshot.values():
                widget.on_descriptor_reading(reading, descriptor)
        # v0.55.6: knowledge-base overlay only needs the chip-style
        # connected state for its embedded chat panel; no readings flow.
        if name == "knowledge_base":
            derived_connected = False
            if self._last_reading_time > 0.0:
                derived_connected = (time.monotonic() - self._last_reading_time) < 3.0
            widget.set_connected(derived_connected)
        # Phase II.7: replay connection state into Calibration overlay.
        if name == "calibration":
            derived_connected = False
            if self._last_reading_time > 0.0:
                derived_connected = (time.monotonic() - self._last_reading_time) < 3.0
            widget.set_connected(derived_connected)
        # Phase II.8: replay connection state into Instruments overlay.
        if name == "instruments":
            derived_connected = False
            if self._last_reading_time > 0.0:
                derived_connected = (time.monotonic() - self._last_reading_time) < 3.0
            widget.set_connected(derived_connected)
        # Phase II.9: replay connection state into Experiment overlay.
        if name == "experiment":
            derived_connected = False
            if self._last_reading_time > 0.0:
                derived_connected = (time.monotonic() - self._last_reading_time) < 3.0
            widget.set_connected(derived_connected)
        # B.8: wire overlay signals
        # AnalyticsView is a primary-view QWidget with no `closed`
        # signal — nothing to wire here (the ToolRail drives navigation
        # away from the view). Block intentionally removed per B.8
        # revision 2; overlay-era comment retained as a signpost.
        if name == "experiment" and hasattr(widget, "closed"):
            widget.closed.connect(lambda: self._on_tool_clicked("home"))
            widget.experiment_finalized.connect(lambda: self._on_tool_clicked("home"))
            # IV.2 B.1: overlay landing page delegates experiment
            # creation to the shell's existing NewExperimentDialog —
            # same dialog as TopWatchBar click path, so there is only
            # one creation flow regardless of entry point.
            if hasattr(widget, "experiment_create_requested"):
                widget.experiment_create_requested.connect(self._show_new_experiment_dialog)
            # B.8.0.1: overlay handles phase transitions via own ZMQ calls
            # Populate with latest state
            if self._latest_experiment_status:
                exp = self._latest_experiment_status.get("active_experiment")
                if exp is not None:
                    exp = dict(exp)
                    exp["current_phase"] = self._latest_experiment_status.get("current_phase")
                    exp["app_mode"] = self._latest_experiment_status.get("app_mode")
                widget.set_templates(self._latest_experiment_status.get("templates", []))
                widget.set_experiment(
                    exp,
                    self._latest_experiment_status.get("phases", []),
                )
        # F4: replay shell-level snapshot cache into freshly-opened AnalyticsView.
        # Phase is sourced from _latest_experiment_status (not the snapshot cache)
        # since it drives layout, not widget data.
        if name == "analytics":
            # Always call set_phase exactly once — applies the correct phase
            # layout (or fallback if no active experiment). AnalyticsView no
            # longer applies any layout in __init__, so this call is what
            # constructs widgets in their final position. Without it, active
            # widgets dict would be empty and no data would render.
            _current_phase: str | None = None
            if self._latest_experiment_status:
                _cp = self._latest_experiment_status.get("current_phase")
                _current_phase = str(_cp) if _cp else None
            widget.set_phase(_current_phase)
            for setter_name, args in self._analytics_snapshot.items():
                fn = getattr(widget, setter_name, None)
                if callable(fn):
                    fn(*args)
            if self._analytics_temperature_snapshot:
                widget.set_temperature_readings(dict(self._analytics_temperature_snapshot))
            if self._analytics_keithley_snapshot:
                widget.set_keithley_readings(dict(self._analytics_keithley_snapshot))

    # ------------------------------------------------------------------
    # F4 analytics snapshot cache helper
    # ------------------------------------------------------------------

    def _push_analytics(self, setter_name: str, *args: object) -> None:
        """Cache a last-value analytics setter call and forward to view if open.

        Keeps the shell-level snapshot in sync so that when AnalyticsView is
        first opened (or re-opened after close), _ensure_overlay replays all
        cached values into the fresh instance — preventing the empty-on-open
        UX bug described in F4 (spec §4.5).
        """
        self._analytics_snapshot[setter_name] = args
        if self._analytics_view is not None:
            fn = getattr(self._analytics_view, setter_name, None)
            if callable(fn):
                fn(*args)

    # ------------------------------------------------------------------
    # Reading dispatch — same routing as old MainWindow
    # ------------------------------------------------------------------

    def dispatch_qualified_reading(self, qualified: DescriptorQualifiedReading) -> None:
        """Qualified-ingress entry point — D7.1b Option C.

        Called synchronously on the GUI thread for every reading drained via
        ``poll_readings_with_descriptor()``.  Atomically per reading:

        1. Updates the descriptor store (authoritative / legacy_absent / refused).
           Capacity-exhausted result is logged but never raises.
        2. Delegates the bare reading to all legacy sinks exactly once via
           ``_dispatch_reading()``.  No double dispatch.
        """
        if type(qualified) is not DescriptorQualifiedReading or type(qualified.reading) is not Reading:
            logger.warning("malformed descriptor-qualified reading dropped")
            return

        view: DescriptorView | None = None
        result: IngestResult | None = None
        dashboard_identity = IdentityStatus.REFUSED
        try:
            result = self._descriptor_store.ingest(qualified)
        except RuntimeError:
            raise
        except Exception:
            logger.warning(
                "descriptor ingest failed for channel %s; reading dispatched to legacy sinks",
                qualified.reading.channel,
                exc_info=True,
            )
        else:
            if result is IngestResult.CAPACITY_EXHAUSTED:
                logger.debug(
                    "DescriptorStore capacity exhausted for channel %s; reading still dispatched",
                    qualified.reading.channel,
                )
            else:
                view = self._descriptor_store.view(qualified.reading.channel)
                if view is not None:
                    dashboard_identity = view.identity_status
        self._dispatch_reading(qualified.reading, dashboard_identity)
        if (
            result is IngestResult.ACCEPTED
            and qualified.descriptor is not None
            and view is not None
            and view.identity_status is IdentityStatus.AUTHORITATIVE
        ):
            self._dispatch_descriptor_reading(qualified.reading, view.descriptor)
        if self._instrument_panel is not None:
            self._instrument_panel.on_descriptor_reading(qualified.reading, view)

    def invalidate_descriptor_transport(self) -> None:
        """Advance the store generation after a bridge death/restart.

        Call this whenever the bridge is known to have died or restarted so
        that stale legacy-absent readings arriving in the new session cannot
        silently restore authoritative identity status.
        """
        self._descriptor_store.invalidate_transport()

    @Slot(object)
    def _dispatch_reading(
        self,
        reading: Reading,
        dashboard_identity: IdentityStatus = IdentityStatus.LEGACY_ABSENT,
    ) -> None:
        channel = reading.channel
        # System, analytics, and support messages are informative but cannot
        # establish measurement flow, engine presence, or mutation authority.
        is_measurement = not channel.startswith(("system/", "analytics/", "support/"))
        if is_measurement:
            self._reading_count += 1
            self._rate_count += 1
            self._last_reading_time = time.monotonic()

        # Eager sinks
        self._overview_panel.on_reading(reading, dashboard_identity)
        try:
            self._top_bar.on_reading(reading)
        except Exception:
            logger.warning("TopWatchBar reading dispatch failed", exc_info=True)

        if channel == "system/disk_free_gb":
            self._dispatch_disk_evidence(reading)

        # Lazy sinks — only route if the panel has been opened at least once
        # B.8.0.2: route log entries to overlay for live timeline
        if channel == "analytics/operator_log_entry" and self._experiment_overlay is not None:
            self._experiment_overlay.on_reading(reading)
        if (
            channel
            in {
                "analytics/keithley_channel_state/smua",
                "analytics/keithley_channel_state/smub",
            }
            and self._keithley_panel is not None
        ):
            self._keithley_panel.on_reading(reading)
        if channel.startswith("analytics/"):
            # Note: _overview_panel.on_reading already called above in
            # eager sinks — no need to call again here (B.5.5 F3)
            # B.8: the v2 AnalyticsView exposes set_cooldown /
            # set_r_thermal setters instead of a generic on_reading sink.
            # The shell adapts specific analytics channels into the typed
            # snapshots below.
            # F4: _adapt_reading_to_analytics now handles None view internally
            # via _push_analytics — remove the prior None guard.
            self._adapt_reading_to_analytics(reading)
            if self._operator_log_panel is not None:
                self._operator_log_panel.on_reading(reading)
            if channel == "analytics/safety_state":
                self._dispatch_safety_evidence(reading)

    def _current_bridge_instance_id(self) -> str | None:
        value = getattr(self._bridge, "bridge_instance_id", None)
        return value if type(value) is str and len(value) == 32 else None

    def _dispatch_safety_evidence(self, reading: Reading) -> None:
        """Present ordered legacy telemetry without outranking typed authority."""
        if self._replay_mode:
            self._last_safety_state = None
            self._last_safety_reason = ""
            self._invalidate_safety_authority(
                "Режим replay — текущее состояние Safety неизвестно",
                disconnected=True,
            )
            return
        metadata = reading.metadata
        if type(metadata) is not dict:
            self._invalidate_safety_authority("Некорректное состояние Safety")
            return
        state_name = metadata.get("state")
        if type(state_name) is not str or not state_name:
            self._invalidate_safety_authority("Некорректное состояние Safety")
            return
        if (
            type(reading.timestamp) is not datetime
            or reading.timestamp.tzinfo is None
            or reading.timestamp.utcoffset() is None
        ):
            self._invalidate_safety_authority("Время состояния Safety не подтверждено")
            return
        observed_at = reading.timestamp.astimezone(UTC)
        wall_now = datetime.now(UTC)
        if observed_at > wall_now + timedelta(seconds=_SAFETY_FUTURE_TOLERANCE_S):
            self._invalidate_safety_authority("Состояние Safety получено из будущего")
            return
        if observed_at < wall_now - timedelta(seconds=_SAFETY_MAX_SOURCE_AGE_S):
            self._invalidate_safety_authority("Состояние Safety устарело")
            return
        if self._last_safety_observed_at is not None and observed_at <= self._last_safety_observed_at:
            if state_name not in _SAFETY_READY_STATES:
                self._invalidate_safety_authority("Нарушен порядок состояния Safety")
            return
        reason = metadata.get("reason", "") or ""
        if self._typed_safety_authority_seen:
            # READY-looking analytics cannot overwrite the coherent typed cut.
            # A negative observation is allowed to revoke it, and remains
            # visible until a newer typed cut supplies recovery authority.
            if state_name not in _SAFETY_READY_STATES:
                self._last_safety_state = state_name
                self._last_safety_reason = str(reason) if reason else ""
                self._last_safety_observed_at = observed_at
                self._bottom_bar.set_safety_state(self._last_safety_state)
                self._invalidate_safety_authority(self._last_safety_reason or "Safety state is not ready")
            return

        self._last_safety_state = state_name
        self._last_safety_reason = str(reason) if reason else ""
        self._last_safety_observed_at = observed_at
        self._bottom_bar.set_safety_state(self._last_safety_state)

        # Analytics is presentation telemetry, not command authority. It may
        # revoke a previously accepted typed cut, but even a fresh, matching
        # READY-looking packet cannot create bindings or restore mutation
        # readiness. Recovery requires a newer coherent OperatorSnapshot.
        if state_name not in _SAFETY_READY_STATES:
            self._invalidate_safety_authority(self._last_safety_reason or "Safety state is not ready")
        else:
            self._accepted_safety_bridge_instance_id = None
            self._accepted_safety_experiment_id = None
            if self._keithley_panel is not None:
                self._keithley_panel.set_safety_ready(
                    False,
                    "No authoritative Safety state",
                )

    def _current_keithley_safety_gate(self) -> tuple[bool, str]:
        bridge_instance_id = self._current_bridge_instance_id()
        binding_current = (
            bridge_instance_id is not None
            and self._accepted_safety_bridge_instance_id == bridge_instance_id
            and (
                self._latest_experiment_status is None
                or self._accepted_safety_experiment_id == self._active_experiment_id()
            )
        )
        if self._typed_safety_authority_seen and self._typed_safety_ready and binding_current:
            return True, ""
        if self._typed_safety_authority_seen:
            return False, self._last_safety_reason or "Нет текущего состояния Safety"
        return False, self._last_safety_reason or "Нет авторитетного состояния Safety"

    def _invalidate_safety_authority(self, reason: str, *, disconnected: bool = False) -> None:
        self._accepted_safety_bridge_instance_id = None
        self._accepted_safety_experiment_id = None
        self._typed_safety_ready = False
        if self._last_safety_state is not None:
            self._bottom_bar.set_safety_state(self._last_safety_state, stale=True)
        elif disconnected:
            self._bottom_bar.set_safety_state(None, stale=True)
        if self._keithley_panel is not None:
            self._keithley_panel.set_safety_ready(False, reason)

    def _dispatch_disk_evidence(self, reading: Reading) -> None:
        """Accept only current, ordered disk evidence from this bridge instance."""
        bridge = self._bridge
        bridge_instance_id = getattr(bridge, "bridge_instance_id", None)
        metadata = reading.metadata
        if (
            bridge is None
            or type(bridge_instance_id) is not str
            or len(bridge_instance_id) != 32
            or type(metadata) is not dict
        ):
            return
        if metadata.get("bridge_instance_id") != bridge_instance_id:
            if self._accepted_disk_bridge_instance_id not in (None, bridge_instance_id):
                self._last_disk_observed_at = None
                self._accepted_disk_bridge_instance_id = None
                self._bottom_bar.mark_disk_stale(disconnected=False)
            return
        if (
            reading.instrument_id != "system"
            or reading.unit != "GB"
            or type(reading.timestamp) is not datetime
            or reading.timestamp.tzinfo is None
            or reading.timestamp.utcoffset() is None
        ):
            return
        observed_at = reading.timestamp.astimezone(UTC)
        now = datetime.now(UTC)
        if observed_at > now + timedelta(seconds=_DISK_FUTURE_TOLERANCE_S):
            return
        if observed_at < now - timedelta(seconds=_DISK_MAX_SOURCE_AGE_S):
            self._bottom_bar.mark_disk_stale(disconnected=False)
            return
        previous_instance = self._accepted_disk_bridge_instance_id
        if previous_instance is not None and previous_instance != bridge_instance_id:
            # A new bridge is a new authority. Never let prior-instance disk
            # truth continue to look current while awaiting its first cut.
            self._last_disk_observed_at = None
            self._bottom_bar.mark_disk_stale(disconnected=False)
        if self._last_disk_observed_at is not None and observed_at <= self._last_disk_observed_at:
            return
        if self._bottom_bar.set_disk_evidence(
            reading.value,
            source=metadata.get("source", ""),
            state=metadata.get("operator_state", ""),
        ):
            self._last_disk_observed_at = observed_at
            self._accepted_disk_bridge_instance_id = bridge_instance_id

    def _dispatch_descriptor_reading(
        self,
        reading: Reading,
        descriptor: ChannelDescriptorV1,
    ) -> None:
        """Route authoritative readings to metadata-selected specialist sinks.

        Bare, legacy, refused, or capacity-exhausted readings never enter this
        path. They remain visible through the eager generic sinks and the
        descriptor-aware instrument panel, without acquiring control authority.
        """
        quantity = descriptor.quantity

        if quantity is ChannelQuantity.RAW_SENSOR and self._calibration_panel is not None:
            self._calibration_panel.on_reading(reading)

        if quantity is ChannelQuantity.TEMPERATURE:
            if self._conductivity_panel is not None:
                self._conductivity_panel.on_reading(reading)
            self._analytics_temperature_snapshot[descriptor.channel_id] = reading
            if self._analytics_view is not None:
                self._analytics_view.set_temperature_readings({descriptor.channel_id: reading})

            if _is_manifest_cold_stage_descriptor(descriptor):
                self._push_analytics("set_cold_temperature_reading", reading)
        is_source_readback = (
            descriptor.role is ChannelRole.SOURCE_READBACK
            and descriptor.safety_class is ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK
        )
        if is_source_readback:
            if self._keithley_panel is not None:
                self._keithley_panel.on_reading(reading)
            if quantity is ChannelQuantity.POWER and self._conductivity_panel is not None:
                self._conductivity_panel.on_reading(reading)
            if quantity in {
                ChannelQuantity.VOLTAGE,
                ChannelQuantity.CURRENT,
                ChannelQuantity.POWER,
            }:
                self._analytics_keithley_snapshot[descriptor.channel_id] = reading
                if self._analytics_view is not None:
                    self._analytics_view.set_keithley_readings({descriptor.channel_id: reading})

        if quantity is ChannelQuantity.PRESSURE:
            self._push_analytics("set_pressure_reading", reading)

        if is_manifest_multiline_descriptor(descriptor):
            self._multiline_snapshot[descriptor.channel_id] = (reading, descriptor)
            if self._multiline_panel is not None:
                self._multiline_panel.on_descriptor_reading(reading, descriptor)

    # ------------------------------------------------------------------
    # Analytics channel adapter (B.8 follow-up)
    # ------------------------------------------------------------------

    def _adapt_reading_to_analytics(self, reading: Reading) -> None:
        """Translate broker ``analytics/*`` readings into AnalyticsView setter calls.

        Routes known analytics channels through :meth:`_push_analytics` so that
        the shell-level snapshot cache is updated regardless of whether
        AnalyticsView is currently open (F4 lazy-open replay, spec §4.5).

        Any unrecognised ``analytics/*`` channel is silently dropped — the v2
        panel has no generic ``on_reading`` sink, so unknown channels are
        intentional no-ops.
        """
        channel = reading.channel
        if channel == "analytics/cooldown_predictor/cooldown_eta":
            data = self._cooldown_reading_to_data(reading)
            if data is not None:
                self._push_analytics("set_cooldown", data)
        elif channel.startswith("analytics/r_thermal"):
            # R_thermal live reading — forward metadata as RThermalData.
            from cryodaq.gui.shell.views.analytics_view import RThermalData

            meta = reading.metadata or {}
            history = meta.get("history") or []
            self._push_analytics(
                "set_r_thermal",
                RThermalData(
                    current_value=float(reading.value) if reading.value is not None else None,
                    delta_per_minute=meta.get("delta_per_minute"),
                    last_updated_ts=reading.timestamp.timestamp(),
                    history=list(history),
                ),
            )
        elif channel == "analytics/instrument_health":
            health = reading.metadata.get("health") if reading.metadata else None
            self._push_analytics("set_instrument_health", health)
        elif channel == "analytics/vacuum_prediction":
            prediction = reading.metadata if reading.metadata else None
            self._push_analytics("set_vacuum_prediction", prediction)

    @staticmethod
    def _cooldown_reading_to_data(reading: Reading):
        """Build a `CooldownData` snapshot from a cooldown_predictor reading.

        Plugin output shape (see cooldown_service.py:400-433):
          - value              = t_remaining_hours (also in metadata)
          - metadata["t_remaining_hours"]   float, hours
          - metadata["t_remaining_ci68"]    (low, high) asymmetric
          - metadata["progress"]            float in [0, 1]  (fraction, NOT %)
          - metadata["phase"]               "phase1" | "transition" | "phase2" | "steady"
          - metadata["future_t"]            optional list[float], hours
          - metadata["future_T_cold_mean"]  optional list[float], K
          - metadata["future_T_cold_upper"] optional list[float], K
          - metadata["future_T_cold_lower"] optional list[float], K
        """
        # Lazy import — avoids a hard dependency at module-load time.
        from cryodaq.gui.shell.views.analytics_view import CooldownData

        meta = reading.metadata or {}
        try:
            t_hours = float(meta.get("t_remaining_hours", reading.value))
        except (TypeError, ValueError):
            return None

        # Asymmetric CI (low, high) → conservative symmetric half-width.
        # Spec's CooldownData uses a single ±ci value; picking the larger
        # side preserves the worst case rather than hiding it.
        ci_hours = 0.0
        ci_tuple = meta.get("t_remaining_ci68")
        if isinstance(ci_tuple, (tuple, list)) and len(ci_tuple) == 2:
            try:
                low_ci, high_ci = float(ci_tuple[0]), float(ci_tuple[1])
                ci_hours = max(high_ci - t_hours, t_hours - low_ci, 0.0)
            except (TypeError, ValueError):
                ci_hours = 0.0

        progress_raw = meta.get("progress", 0.0)
        try:
            progress_pct = max(0.0, min(100.0, float(progress_raw) * 100.0))
        except (TypeError, ValueError):
            progress_pct = 0.0

        # Phase remap: plugin emits "steady" for p ≥ 0.98; spec uses
        # "stabilizing". The spec's "complete" state is NOT distinguished
        # by the plugin today, so it never flows through this adapter.
        plugin_phase = str(meta.get("phase", "") or "")
        phase = "stabilizing" if plugin_phase == "steady" else plugin_phase

        # Trajectories: plugin publishes PREDICTED future only. Actual
        # trajectory stays empty until a publisher is added; the cooldown
        # plot's actual-line will simply render no points.
        predicted: list = []
        ci_traj: list = []
        future_t = meta.get("future_t")
        future_mean = meta.get("future_T_cold_mean")
        future_upper = meta.get("future_T_cold_upper")
        future_lower = meta.get("future_T_cold_lower")
        # future_t is hours-from-now (plugin contract). Convert to absolute
        # Unix timestamps so CooldownPredictionWidget's DateAxisItem renders
        # a human-readable date rather than 1970-01-01.
        future_t_abs: list[float] = []
        if isinstance(future_t, list):
            import time as _time

            now_ts = _time.time()
            future_t_abs = [now_ts + float(h) * 3600.0 for h in future_t]
        if future_t_abs and isinstance(future_mean, list) and len(future_t_abs) == len(future_mean):
            predicted = list(zip(future_t_abs, future_mean, strict=False))
        if (
            future_t_abs
            and isinstance(future_upper, list)
            and isinstance(future_lower, list)
            and len(future_t_abs) == len(future_upper) == len(future_lower)
        ):
            ci_traj = list(zip(future_t_abs, future_lower, future_upper, strict=False))

        return CooldownData(
            t_hours=t_hours,
            ci_hours=ci_hours,
            phase=phase,
            progress_pct=progress_pct,
            actual_trajectory=[],
            predicted_trajectory=predicted,
            ci_trajectory=ci_traj,
            phase_boundaries_hours=[],
        )

    # ------------------------------------------------------------------
    # Bottom bar tick
    # ------------------------------------------------------------------

    @Slot()
    def _tick_status(self) -> None:
        now = time.monotonic()
        silence = now - self._last_reading_time if self._last_reading_time > 0 else 999.0
        connected = silence < 3.0
        wall_now = datetime.now(UTC)
        current_bridge_instance_id = self._current_bridge_instance_id()
        disk_marked_stale = False
        if (
            self._accepted_disk_bridge_instance_id is not None
            and self._accepted_disk_bridge_instance_id != current_bridge_instance_id
        ):
            # Bridge replacement is an authority boundary: clear both halves
            # of the accepted record before presenting the retained history.
            self._accepted_disk_bridge_instance_id = None
            self._last_disk_observed_at = None
            self._bottom_bar.mark_disk_stale(disconnected=not connected)
            disk_marked_stale = True
        elif self._last_disk_observed_at is not None and self._last_disk_observed_at < wall_now - timedelta(
            seconds=_DISK_MAX_SOURCE_AGE_S
        ):
            self._bottom_bar.mark_disk_stale(disconnected=not connected)
            disk_marked_stale = True

        safety_binding_changed = (
            self._accepted_safety_bridge_instance_id is not None
            and self._accepted_safety_bridge_instance_id != current_bridge_instance_id
        )
        safety_experiment_changed = (
            self._accepted_safety_bridge_instance_id is not None
            and self._latest_experiment_status is not None
            and self._accepted_safety_experiment_id != self._active_experiment_id()
        )
        safety_source_expired = (
            not self._typed_safety_authority_seen
            and self._last_safety_observed_at is not None
            and self._last_safety_observed_at < wall_now - timedelta(seconds=_SAFETY_MAX_SOURCE_AGE_S)
        )
        if safety_binding_changed:
            self._invalidate_safety_authority("Поколение связи Safety изменилось")
        elif safety_experiment_changed:
            self._invalidate_safety_authority("Эксперимент Safety изменился")
        elif safety_source_expired:
            self._invalidate_safety_authority("Состояние Safety устарело")
        # Engine state derives from data flow — single source of truth
        self._top_bar.set_engine_state(connected)
        self._overview_panel.set_connected(connected)
        if connected:
            elapsed = now - self._last_rate_time
            rate = self._rate_count / elapsed if elapsed > 0 else 0
            self._rate_count = 0
            self._last_rate_time = now
            self._bottom_bar.set_data_rate(rate)
            self._bottom_bar.set_connected(True, "Подключено")
        else:
            if self._reading_count == 0:
                self._bottom_bar.set_connected(False, "Отключено")
            elif silence < 90:
                self._bottom_bar.set_connected(False, "Нет данных")
            else:
                self._bottom_bar.set_connected(False, "Engine потерян")
            # Engine data flow lost — retain the last known state as evidence,
            # but visibly revoke its current-truth claim and force controls
            # not-ready. The GUI never erases operator evidence into a quiet
            # blank or presents a stale runtime state as current.
            if self._last_safety_state is not None:
                self._invalidate_safety_authority(
                    "Engine потерян — состояние безопасности неизвестно",
                    disconnected=True,
                )
            if not disk_marked_stale:
                self._bottom_bar.mark_disk_stale(disconnected=True)
        # Mirror connection state onto Keithley overlay. Guard on lazy
        # construction — panel may not exist yet.
        if self._keithley_panel is not None:
            self._keithley_panel.set_connected(connected)
        # Phase II.3: mirror to OperatorLog overlay (same contract).
        if self._operator_log_panel is not None:
            self._operator_log_panel.set_connected(connected)
        # Phase II.2: mirror to Archive overlay (same contract).
        if self._archive_panel is not None:
            self._archive_panel.set_connected(connected)
        # Phase II.5: mirror to Conductivity overlay (same contract).
        if self._conductivity_panel is not None:
            self._conductivity_panel.set_connected(connected)
        if self._multiline_panel is not None:
            self._multiline_panel.set_connected(connected)
        # Phase II.7: mirror to Calibration overlay (same contract).
        if self._calibration_panel is not None:
            self._calibration_panel.set_connected(connected)
        # Phase II.4: mirror to Alarm overlay (gates v2 polling + ACK buttons).
        if self._alarm_panel is not None:
            self._alarm_panel.set_connected(connected)
        # Phase II.8: mirror to Instruments overlay (gates 10 s diag polling).
        if self._instrument_panel is not None:
            self._instrument_panel.set_connected(connected)
        # Phase II.9: mirror to Experiment overlay (gates action buttons).
        if self._experiment_overlay is not None:
            self._experiment_overlay.set_connected(connected)

    def closeEvent(self, event):  # noqa: ANN001
        """Teardown: stop the status timer and join the experiment-create worker
        (the only ZmqCommandWorker this window owns directly) before the C++
        objects are destroyed, so we don't trip Qt's "QThread: Destroyed while
        thread is still running" on exit. Panel-owned workers self-clean via
        their own ``_WorkerCleanupMixin.closeEvent``. Bounded + guarded so
        teardown can never hang."""
        try:
            self._status_timer.stop()
        except RuntimeError:
            pass
        controller = getattr(self, "_annunciation_controller", None)
        if controller is not None:
            try:
                if not controller.shutdown():
                    logger.critical("Annunciation controller did not settle all owned workers during GUI shutdown")
                    event.ignore()
                    return
            except RuntimeError:
                logger.critical("Annunciation controller shutdown could not establish worker settlement", exc_info=True)
                event.ignore()
                return
        worker = getattr(self, "_create_exp_worker", None)
        if worker is not None:
            try:
                if worker.isRunning():
                    worker.wait(2000)
            except RuntimeError:
                pass
        # Child overlays may own command workers independently of the
        # annunciation controller. Snapshot the descendants first, then try
        # every valid owner even if one wrapper is already deleting. A single
        # RuntimeError must not prevent later workers from being joined.
        settlement_failures: list[str] = []
        try:
            candidates = list(self.findChildren(QThread))
        except RuntimeError:
            candidates = []
            settlement_failures.append("QThread descendant inventory unavailable")
        for index, thread in enumerate(candidates):
            owner = f"QThread[{index}]"
            try:
                if thread.isRunning():
                    thread.requestInterruption()
                    thread.quit()
                    if not thread.wait(_WORKER_SETTLE_MS):
                        settlement_failures.append(f"{owner} did not settle")
                        continue
                # Join first, then consolidate QObject ownership under the
                # closing window.  Reparenting settled workers to the global
                # application leaked them past window teardown and could race
                # deferred deletion of their former nested parent.
                if thread.parent() is not self:
                    thread.setParent(self)
            except RuntimeError:
                settlement_failures.append(f"{owner} became invalid during shutdown")
                continue
        if settlement_failures:
            logger.critical("GUI child QThread shutdown incomplete: %s", "; ".join(settlement_failures))
            event.ignore()
            return
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # More-menu actions ported from launcher
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Experiment lifecycle (B.8)
    # ------------------------------------------------------------------

    def _on_experiment_status_received(self, status: dict) -> None:
        """Forward status to dashboard + overlay, cache for routing."""
        previous_exp_id = self._active_experiment_id()
        self._latest_experiment_status = status

        # F4: invalidate experiment-scoped analytics snapshot on boundary.
        # Accumulating caches (temperature, keithley) and cooldown are
        # tied to one experiment; clear them when the active experiment changes
        # so a newly-opened AnalyticsView does not replay stale data.
        active = status.get("active_experiment")
        new_exp_id = active.get("experiment_id") if isinstance(active, dict) else None
        if (
            self._accepted_safety_bridge_instance_id is not None
            and new_exp_id != self._accepted_safety_experiment_id
            and new_exp_id != previous_exp_id
        ):
            self._invalidate_safety_authority("Эксперимент Safety изменился")
        if new_exp_id != self._analytics_last_exp_id:
            self._analytics_snapshot.pop("set_cooldown", None)
            self._analytics_snapshot.pop("set_experiment_status", None)
            self._analytics_temperature_snapshot.clear()
            self._analytics_keithley_snapshot.clear()
            self._analytics_last_exp_id = new_exp_id

        self._overview_panel.on_experiment_status(status)
        # Forward to overlay if it exists and is visible
        if self._experiment_overlay is not None:
            exp = status.get("active_experiment")
            if exp is not None:
                # Inject top-level fields into experiment dict for overlay
                exp = dict(exp)
                exp["current_phase"] = status.get("current_phase")
                exp["app_mode"] = status.get("app_mode")
            phases = status.get("phases", [])
            self._experiment_overlay.set_experiment(exp, phases)
        # Phase II.3: push current experiment id to OperatorLog overlay.
        if self._operator_log_panel is not None:
            self._operator_log_panel.set_current_experiment(self._active_experiment_id())
        # Phase III.C: propagate current phase into AnalyticsView so its
        # dynamic layout can swap to the phase-appropriate widget set.
        if self._analytics_view is not None:
            current_phase = status.get("current_phase")
            self._analytics_view.set_phase(str(current_phase) if current_phase else None)
        # F3-Cycle4: W3 experiment_summary — forward full status for replay.
        self._push_analytics("set_experiment_status", status)

    def _active_experiment_id(self) -> str | None:
        """Return the cached active experiment id, or None."""
        if not self._latest_experiment_status:
            return None
        active = self._latest_experiment_status.get("active_experiment")
        if not isinstance(active, dict):
            return None
        value = active.get("experiment_id")
        return str(value) if value is not None else None

    def _on_experiment_clicked(self) -> None:
        """TopWatchBar experiment label click — open overlay or dialog."""
        has_active = (
            self._latest_experiment_status is not None
            and self._latest_experiment_status.get("active_experiment") is not None
        )
        if has_active or self._replay_mode:
            self._on_tool_clicked("experiment")
        else:
            self._show_new_experiment_dialog()

    def _show_new_experiment_dialog(self) -> None:

        if self._replay_mode:
            logger.warning("Replay mode rejected experiment creation dialog")
            return

        templates = []
        if self._latest_experiment_status:
            templates = self._latest_experiment_status.get("templates", [])
        dialog = NewExperimentDialog(self, available_templates=templates)
        dialog.experiment_create_requested.connect(self._on_create_experiment)
        dialog.exec()

    def _on_create_experiment(self, payload: dict) -> None:
        if self._replay_mode:
            logger.warning("Replay mode rejected experiment_create dispatch")
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        cmd = {"cmd": "experiment_create", **payload}
        self._create_exp_worker = ZmqCommandWorker(cmd, parent=self)
        self._create_exp_worker.finished.connect(self._on_create_exp_result)
        self._create_exp_worker.start()

    def _on_create_exp_result(self, result: dict) -> None:
        if not result.get("ok"):
            logger.warning("experiment_create failed: %s", result.get("error"))
            return
        # Status poll will pick up new experiment, dashboard updates automatically
        logger.info("Experiment created: %s", result.get("experiment_id", "?"))

    # ------------------------------------------------------------------
    # Other tool actions
    # ------------------------------------------------------------------

    def _open_web_panel(self) -> None:
        import socket
        import webbrowser

        from PySide6.QtWidgets import QMessageBox

        from cryodaq.launcher import _WEB_PORT  # constant only

        host = "127.0.0.1"
        try:
            with socket.create_connection((host, _WEB_PORT), timeout=0.5):
                pass
        except (TimeoutError, OSError):
            QMessageBox.information(
                self,
                "Web-панель",
                f"Веб-сервер не запущен на порту {_WEB_PORT}.\n\n"
                f"Запустите его командой:\n"
                f"uvicorn cryodaq.web.server:app --host 127.0.0.1 --port {_WEB_PORT}",
            )
            return
        webbrowser.open(f"http://{host}:{_WEB_PORT}")

    def _restart_engine(self) -> None:
        """Restart engine subprocess.

        When embedded in LauncherWindow, walks up the parent chain to
        find the launcher and delegates. In standalone mode (cryodaq-gui)
        the engine is owned by another process so the action surfaces a
        message instead of attempting a restart.
        """
        from PySide6.QtWidgets import QMessageBox

        if self._replay_mode:
            logger.warning("Replay mode rejected Engine restart")
            return

        reply = QMessageBox.question(
            self,
            "Перезапуск Engine",
            "Перезапустить Engine?\n\nЗапись данных будет прервана на несколько секунд.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        host = self._find_launcher_host()
        if host is not None:
            host._on_restart_engine_from_shell()
            return
        QMessageBox.information(
            self,
            "Перезапуск Engine",
            "Перезапуск Engine доступен только при запуске через лаунчер.",
        )

    def _find_launcher_host(self):
        parent = self.parent()
        while parent is not None:
            if parent.__class__.__name__ == "LauncherWindow":
                return parent
            parent = parent.parent() if callable(getattr(parent, "parent", None)) else None
        return None
