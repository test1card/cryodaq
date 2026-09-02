"""Phase UI-1 v2 dashboard — replaces legacy OverviewPanel.

Five vertically stacked zones. B.2 fills tempPlotZone and
pressurePlotZone with real pyqtgraph widgets. B.3 fills
sensorGridZone with DynamicSensorGrid. Other zones remain
placeholder until B.4-B.6.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from typing import Any

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QLayout, QScrollArea, QVBoxLayout, QWidget

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.core.phase_labels import PHASE_ORDER
from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore
from cryodaq.gui.dashboard.dynamic_sensor_grid import DynamicSensorGrid
from cryodaq.gui.dashboard.phase_aware_widget import PhaseAwareWidget
from cryodaq.gui.dashboard.pressure_plot_widget import PressurePlotWidget
from cryodaq.gui.dashboard.quick_log_block import QuickLogBlock
from cryodaq.gui.dashboard.temp_plot_widget import TempPlotWidget
from cryodaq.gui.shell.overlays.operator_log_panel import (
    bounded_operator_log_identity,
    decode_operator_log_unresolved,
    encode_operator_log_unresolved,
    operator_log_commit_receipt_matches,
)
from cryodaq.gui.state.descriptor_store import IdentityStatus
from cryodaq.operator_snapshot import (
    OperatorPresentationState,
    OperatorSnapshot,
    ReadinessTruth,
    SafetyLifecycle,
    SnapshotMode,
)

logger = logging.getLogger(__name__)

# How far back a reconnect tries to refill the plots. 24 h covers a cooldown,
# which is the run people watch across a relaunch; the buffers bound it anyway.
_HISTORY_SEED_SPAN_S = 24 * 3600
_HISTORY_SEED_LIMIT = 20000

_PRESENTATION_INTERVAL_MS = 500  # DESIGN: RULE-DATA-002 — at most 2 Hz
_LOG_COMMIT_SCHEMA = "operator_log_commit_v1"
_LOG_READ_SCOPE_SCHEMA = "operator_log_read_scope_v1"
_EXPERIMENT_COMMIT_SCHEMA = "experiment_command_commit_v1"
_DASHBOARD_UNRESOLVED_SETTINGS_KEY = "dashboard/unresolved_operator_log_v1"
_KNOWN_UNCOMMITTED_LOG_ERRORS = frozenset(
    {
        "mutation_protocol_incompatible",
        "operator_log_request_id_invalid",
        "operator_log_scope_invalid",
        "stale_experiment_command",
        "operator_log_message_invalid",
        "operator_log_admission_invalid",
        "engine_shutting_down",
        "idempotency_key_conflict",
        "operator_log_busy",
    }
)


def _log_result_is_unknown(result: object) -> bool:
    """Return whether a reply cannot prove commit or non-commit."""

    if type(result) is not dict:
        return True
    if result.get("_handler_timeout") or result.get("_unknown"):
        return True
    if result.get("committed") is True:
        return False
    return not (
        result.get("ok") is False
        and result.get("committed") is False
        and result.get("error_code") in _KNOWN_UNCOMMITTED_LOG_ERRORS
    )


def _same_cut_ignoring_transport(left: object, right: object) -> bool:
    """Whether two snapshots are the same producer cut.

    Equality alone is the wrong test for a same-revision delivery, because the
    GUI re-derives its OWN transport freshness: OperatorSnapshotIngress polls
    every 0.5 s and, on any tick that drains no new cut, re-emits the stored
    snapshot with an updated ``status.transport_age_s``. Snapshots arrive at
    ~1 Hz, so roughly every other delivery was a same-revision refresh that
    compared unequal — revoking mutation authority and making every gated
    control flap at about 1 Hz.

    A transport age the GUI advanced by itself is not the producer
    contradicting itself, so ``transport_age_s`` is ignored here. EVERYTHING
    else still counts: a second producer cut under one revision differs in
    ``cut.observed_at``/``received_at`` and is still equivocation, which the
    caller revokes on. Transport genuinely degrading is caught separately, by
    the ``valid`` recomputation (state/reason codes), not by this comparison.
    """
    if dataclasses.is_dataclass(left) and dataclasses.is_dataclass(right):
        if type(left) is not type(right):
            return False
        for field in dataclasses.fields(left):
            if field.name == "transport_age_s":
                continue
            if not _same_cut_ignoring_transport(getattr(left, field.name), getattr(right, field.name)):
                return False
        return True
    return bool(left == right)


# Zone definitions: (objectName, label_or_None, stretch)
# label_or_None=None means the zone is filled by a real widget, not placeholder.
_ZONES = [
    ("phaseZone", "[ФАЗА ЭКСПЕРИМЕНТА — будет в B.4]", 4),
    ("sensorGridZone", "[ДАТЧИКИ — будет в B.3]", 22),
    ("tempPlotZone", None, 50),
    ("pressurePlotZone", None, 18),
    ("quickLogZone", "[ЖУРНАЛ — будет в B.6]", 4),
]


class DashboardView(QScrollArea):
    """Phase UI-1 v2 dashboard — replaces legacy OverviewPanel."""

    def __init__(
        self,
        channel_manager: ChannelManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = QSettings("FIAN", "CryoDAQ")
        self._channel_mgr = channel_manager
        self._buffer_store = ChannelBufferStore()
        self._history_seed_worker: object | None = None
        self._temp_plot: TempPlotWidget | None = None
        self._pressure_plot: PressurePlotWidget | None = None
        self._sensor_grid: DynamicSensorGrid | None = None
        self._phase_widget: PhaseAwareWidget | None = None
        self._quick_log: QuickLogBlock | None = None
        self._connected = False
        self._connection_generation = 0
        self._read_only = False
        self._phase_worker = None
        self._phase_context: dict[str, Any] | None = None
        self._phase_reconcile_worker = None
        self._authority_valid = False
        self._authority_experiment_id: str | None = None
        self._authority_producer_id: str | None = None
        self._authority_revision: int | None = None
        self._authority_snapshot: OperatorSnapshot | None = None
        self._log_submit_worker = None
        self._log_submit_context: dict[str, Any] | None = None
        self._log_unresolved_context: dict[str, Any] | None = None
        self._log_poll_worker = None
        self._log_poll_context: dict[str, Any] | None = None
        self._log_poll_pending = False
        self._build_ui()
        restored = decode_operator_log_unresolved(self._settings.value(_DASHBOARD_UNRESOLVED_SETTINGS_KEY, ""))
        if restored is not None:
            self._log_unresolved_context = restored
            if self._quick_log is not None:
                self._quick_log._input.setText(restored["message"])
                self._quick_log.set_submission_state(
                    "unknown",
                    "Найдена незавершённая запись. Текст сохранён, повтор сверит тот же ключ.",
                )
        self._update_mutation_authority()
        self._wire_x_link()
        self._start_refresh_timer()

    def _build_ui(self) -> None:
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAccessibleName("Панель мониторинга")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._content = QWidget()
        self._content.setObjectName("dashboardContent")
        self.setWidget(self._content)

        root = QVBoxLayout(self._content)
        root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        root.setContentsMargins(
            theme.SPACE_2,
            theme.SPACE_2,
            theme.SPACE_2,
            theme.SPACE_2,
        )
        root.setSpacing(theme.SPACE_2)

        for obj_name, label_text, stretch in _ZONES:
            if obj_name == "tempPlotZone":
                zone = self._make_zone(obj_name, None)
                self._temp_plot = TempPlotWidget(
                    self._buffer_store,
                    self._channel_mgr,
                )
                zone.layout().addWidget(self._temp_plot)
            elif obj_name == "pressurePlotZone":
                zone = self._make_zone(obj_name, None)
                self._pressure_plot = PressurePlotWidget(self._buffer_store)
                zone.layout().addWidget(self._pressure_plot)
            elif obj_name == "phaseZone":
                zone = self._make_zone(obj_name, None)
                self._phase_widget = PhaseAwareWidget(parent=self)
                self._phase_widget.phase_transition_requested.connect(self._on_phase_transition_requested)
                zone.layout().addWidget(self._phase_widget)
            elif obj_name == "sensorGridZone":
                zone = self._make_zone(obj_name, None)
                self._sensor_grid = DynamicSensorGrid(
                    self._channel_mgr,
                    self._buffer_store,
                    parent=self._content,
                )
                self._sensor_grid.rename_requested.connect(self._on_rename_requested)
                self._sensor_grid.hide_requested.connect(self._on_hide_requested)
                self._sensor_grid.plot_toggle_requested.connect(self._on_plot_toggle_requested)
                self._sensor_grid.show_on_plot_requested.connect(self._on_show_on_plot_requested)
                self._sensor_grid.history_requested.connect(self._on_history_requested)
                zone.layout().addWidget(self._sensor_grid)
            elif obj_name == "quickLogZone":
                zone = self._make_zone(obj_name, None)
                self._quick_log = QuickLogBlock(parent=self._content)
                self._quick_log.entry_submitted.connect(self._on_log_entry_submitted)
                self._quick_log.set_mutation_enabled(False, "Нет связи с Engine")
                zone.layout().addWidget(self._quick_log)
            else:
                zone = self._make_zone(obj_name, label_text)
            root.addWidget(zone, stretch=stretch)

    @staticmethod
    def _make_zone(name: str, label: str | None) -> QFrame:
        zone = QFrame()
        zone.setObjectName(name)
        zone.setStyleSheet(
            f"#{name} {{ "
            f"background-color: {theme.SURFACE_CARD}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; "
            f"border-radius: {theme.RADIUS_MD}px; "
            f"}}"
        )
        layout = QVBoxLayout(zone)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if label is not None:
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)
        return zone

    def _wire_x_link(self) -> None:
        """Link pressure plot's X axis to the temperature plot."""
        if self._temp_plot is None or self._pressure_plot is None:
            return
        self._pressure_plot._plot.setXLink(self._temp_plot._plot)

    def _start_refresh_timer(self) -> None:
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(_PRESENTATION_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._refresh_plots)
        self._refresh_timer.start()

        # B.7: slower poll for log entries (10s)
        self._log_poll_timer = QTimer(self)
        self._log_poll_timer.setInterval(10000)
        self._log_poll_timer.timeout.connect(self._poll_log_entries)
        self._log_poll_timer.start()

    def _refresh_plots(self) -> None:
        if self._temp_plot is not None:
            self._temp_plot.refresh()
        if self._pressure_plot is not None:
            self._pressure_plot.refresh()
        if self._sensor_grid is not None:
            self._sensor_grid.refresh()

    # ------------------------------------------------------------------
    # Reading ingestion
    # ------------------------------------------------------------------

    def on_reading(
        self,
        reading: Reading,
        identity_status: IdentityStatus = IdentityStatus.LEGACY_ABSENT,
    ) -> None:
        """Route reading into buffer store, grid cells, and phase widget."""
        channel = reading.channel
        value = reading.value
        if not isinstance(value, (int, float)):
            return
        timestamp_epoch = reading.timestamp.timestamp()

        if channel.startswith("\u0422"):  # cyrillic Т
            short_id = channel.split(" ")[0]
            self._buffer_store.append(short_id, timestamp_epoch, float(value), reading.status)
            if self._sensor_grid is not None:
                self._sensor_grid.dispatch_reading(reading, identity_status)
        elif channel.endswith("/pressure"):
            self._buffer_store.append(channel, timestamp_epoch, float(value), reading.status)

        # B.5.5: route analytics readings to phase widget
        if channel.startswith("analytics/") and self._phase_widget is not None:
            self._phase_widget.on_reading(reading)
            if self._read_only:
                self.set_read_only(True)

    def set_read_only(self, read_only: bool) -> None:
        """Keep dashboard evidence visible while removing replay mutations."""

        self._read_only = bool(read_only)
        self._update_mutation_authority()

    def refresh_display_precision(self) -> None:
        """Refresh dashboard measurement text after a preference change."""

        if self._sensor_grid is not None:
            self._sensor_grid.refresh_display_precision()

    def set_connected(self, connected: bool) -> None:
        connected = bool(connected)
        if connected == self._connected:
            return
        self._connected = connected
        self._connection_generation += 1
        if connected:
            self._seed_history_from_engine()
        if not connected:
            self._authority_valid = False
            self._authority_experiment_id = None
            self._authority_producer_id = None
            self._authority_revision = None
            self._authority_snapshot = None
        if not connected and self._log_submit_context is not None:
            self._log_unresolved_context = self._log_submit_context
            if self._quick_log is not None:
                self._quick_log.set_submission_state(
                    "unknown",
                    "Связь потеряна до подтверждения записи; повтор использует тот же ключ операции",
                )
        if not connected and self._phase_context is not None and self._phase_widget is not None:
            self._phase_widget.set_operation_state(
                "unknown",
                "Связь потеряна до сверки смены фазы; команда не будет повторена автоматически",
            )
        if self._quick_log is not None:
            if connected:
                self._quick_log.set_read_stale(
                    "Журнал ещё не подтверждён после восстановления связи; показаны последние данные"
                )
            else:
                self._quick_log.set_read_stale("Связь с Engine потеряна; показаны последние подтверждённые данные")
        self._update_mutation_authority()
        if connected:
            self._poll_log_entries()
            self._start_phase_reconciliation()

    def invalidate_operator_snapshot_producer(self) -> None:
        """Retire the dashboard's producer anchor before engine replacement."""

        if self._connected:
            # Producer replacement is a connection-generation cut for every
            # in-flight dashboard mutation, even when the successor bridge
            # becomes healthy before the ordinary silence timer expires.
            self.set_connected(False)
            return
        self._connection_generation += 1
        self._authority_valid = False
        self._authority_experiment_id = None
        self._authority_producer_id = None
        self._authority_revision = None
        self._authority_snapshot = None
        self._update_mutation_authority()

    def _update_mutation_authority(self) -> None:
        mutable = self._connected and not self._read_only and self._authority_valid
        if self._phase_widget is not None:
            phase_mutable = (
                mutable
                and self._phase_worker is None
                and self._phase_reconcile_worker is None
                and self._phase_context is None
            )
            self._phase_widget.set_mutation_enabled(phase_mutable)
        if self._quick_log is not None:
            if self._read_only:
                reason = "Только чтение"
            elif not self._connected:
                reason = "Нет связи с Engine"
            else:
                reason = "Нет текущего подтверждённого разрешения на изменение"
            self._quick_log.set_mutation_enabled(mutable, reason)
        if self._sensor_grid is not None:
            # Sensor-cell read-only gates ONLY rename and hide, both of which
            # are operator-facing display config in config/channels.yaml with
            # no instrument, source or safety authority. They must stay usable
            # while the stand is unqualified, SAFE_OFF, faulted or
            # disconnected — that is precisely when a channel carrying a wrong
            # name is most dangerous to read. Phase mutations and the quick log
            # above remain gated on full mutation authority; only labelling is
            # released here. Replay is still refused.
            self._sensor_grid.set_read_only(self._read_only)
            # Hiding remains an authority-bearing persisted change.
            self._sensor_grid.set_hide_enabled(mutable)

    def set_operator_snapshot(self, snapshot: object) -> None:
        """Derive mutation authority only from a current live coherent cut."""
        if type(snapshot) is not OperatorSnapshot:
            self._authority_valid = False
            self._authority_experiment_id = None
            self._update_mutation_authority()
            return

        cut = snapshot.cut
        if self._authority_producer_id is None:
            self._authority_producer_id = cut.producer_id
        elif cut.producer_id != self._authority_producer_id:
            # A producer/incarnation replacement is a transport-generation
            # boundary. It must be accompanied by disconnect/reconnect; a
            # READY-looking packet alone cannot seize mutation authority.
            self._authority_valid = False
            self._authority_experiment_id = None
            self._update_mutation_authority()
            return

        previous_revision = self._authority_revision
        valid = (
            cut.mode is SnapshotMode.LIVE
            and snapshot.readiness.readiness is ReadinessTruth.READY
            and snapshot.readiness.lifecycle is SafetyLifecycle.READY
            and snapshot.readiness.status.state is OperatorPresentationState.OK
            and not snapshot.readiness.transport_reason_codes
        )
        if previous_revision is not None:
            if cut.revision < previous_revision:
                self._authority_valid = False
                self._authority_experiment_id = None
                self._update_mutation_authority()
                return
            if cut.revision == previous_revision:
                # Whole-object equality is the wrong divergence test here, and
                # it made every mutation control flap at ~1 Hz.
                #
                # The GUI re-derives its OWN transport freshness:
                # OperatorSnapshotIngress polls every 0.5 s, and on any tick
                # that drains no new cut it calls
                # OperatorSnapshotStore.observe_transport(), which re-emits the
                # SAME revision with an updated transport age. Snapshots arrive
                # at ~1 Hz, so roughly every other delivery was a same-revision
                # refresh that is not object-equal — authority was revoked, the
                # phase buttons and quick log went dead, "нет текущего
                # подтверждённого разрешения на изменение" appeared, and the
                # next real cut restored it. A transport age the GUI itself
                # advanced is not evidence that the producer contradicted
                # itself.
                #
                # Compare the authority-bearing identity instead: producer,
                # runtime domain and experiment. Divergence in any of those,
                # or a cut that is no longer valid, still revokes; and a
                # revision that has already been revoked can never be
                # resurrected without a new one.
                previous = self._authority_snapshot
                same_authority = previous is not None and _same_cut_ignoring_transport(snapshot, previous)
                if not same_authority or not self._authority_valid or not valid:
                    self._authority_valid = False
                    self._authority_experiment_id = None
                self._authority_snapshot = snapshot
                self._update_mutation_authority()
                return

        self._authority_revision = cut.revision
        self._authority_snapshot = snapshot
        self._authority_valid = valid
        self._authority_experiment_id = snapshot.experiment.experiment_id if valid else None
        self._update_mutation_authority()

    # ------------------------------------------------------------------
    # Sensor grid signal handlers
    # ------------------------------------------------------------------

    def _on_rename_requested(self, channel_id: str, new_name: str) -> None:
        """Operator renamed a channel via inline rename or context menu.

        A channel display label is operator-facing presentation held in
        config/channels.yaml. It carries no instrument, source or safety
        authority, so it is deliberately NOT gated on engine connection or
        on the live snapshot's mutation authority: an operator must be able
        to correct a wrong sensor name while the stand is unqualified,
        SAFE_OFF, faulted, or disconnected — which is exactly when a
        mislabelled channel is most dangerous to read.

        Replay remains refused: a historical session must not rewrite the
        live channel configuration.
        """
        if self._read_only:
            return
        self._channel_mgr.set_name(channel_id, new_name)
        self._channel_mgr.save()

    def _on_hide_requested(self, channel_id: str) -> None:
        """Operator wants to hide a channel from the dashboard.

        Still gated on full mutation authority, unlike renaming: hiding
        removes a channel from the operator's view, so it is a persisted
        configuration change the reviewed contract deliberately refuses
        without authority. The context-menu entry is withheld in the same
        condition (see ``set_hide_enabled``) so it is never a silent no-op.
        """
        if self._read_only or not self._connected or not self._authority_valid:
            return
        self._channel_mgr.set_visible(channel_id, False)
        self._channel_mgr.save()

    def _on_plot_toggle_requested(self, channel_id: str) -> None:
        """Operator clicked a sensor card: show or hide its curve.

        Presentation only — it draws no authority and persists nothing, so it
        is deliberately available whenever the cards are (replay included).
        The card dims while its curve is hidden so the plot and the grid
        never disagree about what is being drawn.
        """
        if self._temp_plot is None:
            return
        plotted = not self._temp_plot.is_channel_plotted(channel_id)
        self._temp_plot.set_channel_plotted(channel_id, plotted)
        if self._sensor_grid is not None:
            self._sensor_grid.set_plot_hidden(channel_id, not plotted)

    def _on_show_on_plot_requested(self, channel_id: str) -> None:
        """Stub: plot focus deferred to later block."""
        logger.info("Show on plot requested: %s (stub)", channel_id)

    def _on_history_requested(self, channel_id: str) -> None:
        """Stub: history overlay deferred to later block."""
        logger.info("History requested: %s (stub)", channel_id)

    # ------------------------------------------------------------------
    # Phase widget signal handlers (B.5)
    # ------------------------------------------------------------------

    def _on_phase_transition_requested(self, phase: str) -> None:
        """Forward phase transition request to engine via ZMQ."""
        if (
            self._read_only
            or not self._connected
            or not self._authority_valid
            or self._phase_worker is not None
            or self._phase_reconcile_worker is not None
            or self._phase_context is not None
            or self._phase_widget is None
        ):
            return
        experiment_id = self._phase_widget.active_experiment_id
        if type(experiment_id) is not str or not experiment_id or experiment_id != self._authority_experiment_id:
            self._phase_widget.set_operation_state(
                "error",
                "Нет точного идентификатора активного эксперимента; команда не отправлена",
            )
            return
        # The direct slot remains strict even when invoked outside the visible
        # controls; PHASE_ORDER is the canonical allowlist.
        if phase not in PHASE_ORDER:
            self._phase_widget.set_operation_state("error", "Неизвестная фаза; команда не отправлена")
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        context: dict[str, Any] = {
            "connection_generation": self._connection_generation,
            "experiment_id": experiment_id,
            "phase": phase,
        }
        worker = ZmqCommandWorker(
            {
                "cmd": "experiment_advance_phase",
                "experiment_id": experiment_id,
                "phase": phase,
                "operator": "",
                "expected_experiment_id": experiment_id,
            },
            parent=self,
        )
        worker.finished.connect(
            lambda result, expected=context, completed_worker=worker: self._on_phase_advance_result(
                result, expected, completed_worker
            )
        )
        self._phase_context = context
        self._phase_worker = worker
        self._phase_widget.set_operation_state("pending", "Команда отправлена; ожидается точное подтверждение Engine")
        self._update_mutation_authority()
        worker.start()

    @staticmethod
    def _phase_commit_receipt_matches(result: object, context: dict[str, Any]) -> bool:
        if not isinstance(result, dict) or result.get("committed") is not True:
            return False
        receipt = result.get("commit_receipt")
        phase_entry = result.get("phase")
        return (
            isinstance(receipt, dict)
            and isinstance(phase_entry, dict)
            and receipt.get("schema") == _EXPERIMENT_COMMIT_SCHEMA
            and receipt.get("action") == "experiment_advance_phase"
            and receipt.get("experiment_id") == context.get("experiment_id")
            and receipt.get("committed") is True
            and result.get("experiment_id") == context.get("experiment_id")
            and phase_entry.get("phase") == context.get("phase")
        )

    @staticmethod
    def _phase_result_is_unknown(result: object) -> bool:
        if type(result) is not dict:
            return True
        if result.get("committed") is True or result.get("_handler_timeout") or result.get("_unknown"):
            return True
        if result.get("ok") is False and result.get("error_code"):
            return False
        error = str(result.get("error", "")).casefold()
        return (
            any(
                marker in error
                for marker in ("timeout", "timed out", "тайм-аут", "не отвечает", "may still be running")
            )
            or result.get("ok") is not False
        )

    def _seed_history_from_engine(self) -> None:
        """Fill the plots back to the start of the run, not the start of the process.

        These buffers only ever held live readings, so a relaunch mid-experiment
        showed the operator an empty chart while the PNG reports -- which read
        the database -- showed the whole run. One instrument, two histories, and
        the misleading one is the one on screen during the work.

        The seed is bounded by what the buffers can hold, and the engine clamps
        the request itself; a channel already holding live data keeps it,
        because prefill only fills older than what is there.
        """
        import time

        from cryodaq.gui.zmq_client import ZmqCommandWorker

        if self._history_seed_worker is not None:
            return
        span_s = _HISTORY_SEED_SPAN_S
        now = time.time()
        context = {"connection_generation": self._connection_generation}
        worker = ZmqCommandWorker(
            {
                "cmd": "readings_history",
                "from_ts": now - span_s,
                "to_ts": now,
                "channels": None,
                "limit_per_channel": _HISTORY_SEED_LIMIT,
            },
            parent=self,
        )
        self._history_seed_worker = worker
        worker.finished.connect(
            lambda result, expected=context, completed=worker: self._on_history_seed(result, expected, completed)
        )
        worker.start()

    def _on_history_seed(self, result: dict, expected: dict, completed: object) -> None:
        if completed is self._history_seed_worker:
            self._history_seed_worker = None
        if expected.get("connection_generation") != self._connection_generation:
            # A reconnect happened while this was in flight; its window is stale.
            return
        if not isinstance(result, dict) or result.get("ok") is not True:
            logger.warning("Не удалось загрузить историю для графиков: %s", (result or {}).get("error"))
            return
        data = result.get("data")
        if not isinstance(data, dict):
            return
        seeded = 0
        for channel, points in data.items():
            if not isinstance(channel, str) or not points:
                continue
            try:
                samples = [(float(entry[0]), float(entry[1])) for entry in points]
            except (TypeError, ValueError, IndexError):
                continue
            seeded += self._buffer_store.prefill(channel, samples)
        if seeded:
            logger.info("Графики дополнены историей: %d точек до перезапуска", seeded)
            if self._temp_plot is not None:
                self._temp_plot.refresh()
            if self._pressure_plot is not None:
                self._pressure_plot.refresh()

    def _on_phase_advance_result(
        self,
        result: dict,
        context: dict[str, Any] | None = None,
        worker: Any | None = None,
    ) -> None:
        expected = context or self._phase_context
        if expected is None or self._phase_widget is None:
            return
        if worker is not None and worker is not self._phase_worker:
            return
        if worker is not None:
            self._phase_worker = None
        if expected is not self._phase_context:
            self._update_mutation_authority()
            logger.warning("ignored stale dashboard experiment_advance_phase reply")
            return

        if self._phase_commit_receipt_matches(result, expected):
            self._phase_widget.set_operation_state(
                "pending", "Смена фазы подтверждена; ожидается авторитетное чтение текущей фазы"
            )
            self._start_phase_reconciliation()
            self._update_mutation_authority()
            return
        if self._phase_result_is_unknown(result):
            self._phase_widget.set_operation_state(
                "unknown",
                "Engine не доказал исход смены фазы; команда не повторяется, выполняется чтение-сверка",
            )
            self._start_phase_reconciliation()
            self._update_mutation_authority()
            return

        self._phase_context = None
        error = str(result.get("error", "Engine подтвердил, что фаза не изменена"))
        self._phase_widget.set_operation_state("error", error)
        self._update_mutation_authority()
        logger.warning("advance_phase not committed: %s", error)

    def _start_phase_reconciliation(self) -> None:
        if (
            not self._connected
            or self._phase_context is None
            or self._phase_worker is not None
            or self._phase_reconcile_worker is not None
        ):
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        expected = self._phase_context
        worker = ZmqCommandWorker({"cmd": "experiment_phase_status"}, parent=self)
        worker.finished.connect(
            lambda result, context=expected, completed_worker=worker: self._on_phase_reconciliation_result(
                result, context, completed_worker
            )
        )
        self._phase_reconcile_worker = worker
        self._update_mutation_authority()
        worker.start()

    def _on_phase_reconciliation_result(
        self,
        result: dict,
        context: dict[str, Any],
        worker: Any | None = None,
    ) -> None:
        if worker is not None and worker is not self._phase_reconcile_worker:
            return
        if worker is not None:
            self._phase_reconcile_worker = None
        if context is not self._phase_context or self._phase_widget is None:
            self._update_mutation_authority()
            return
        result_experiment_id = result.get("experiment_id")
        if (
            result.get("ok") is True
            and type(result_experiment_id) is str
            and result_experiment_id != context.get("experiment_id")
        ):
            self._phase_context = None
            self._phase_widget.set_operation_state("error", "Активный эксперимент изменился до сверки старой команды")
            self._update_mutation_authority()
            return
        current_phase = result.get("current_phase")
        exact = (
            result.get("ok") is True
            and result_experiment_id == context.get("experiment_id")
            and (current_phase is None or current_phase in PHASE_ORDER)
        )
        if not exact:
            self._phase_widget.set_operation_state(
                "unknown", "Сверка текущей фазы не удалась; автоматический повтор команды запрещён"
            )
            self._update_mutation_authority()
            if self._connected:
                QTimer.singleShot(5000, self._start_phase_reconciliation)
            return

        target_phase = context["phase"]
        self._phase_widget.on_status_update(
            {
                "active_experiment": {"experiment_id": context["experiment_id"]},
                "current_phase": current_phase,
                "phase_started_at": None,
                "phases": result.get("phases", []),
            }
        )
        self._phase_context = None
        if current_phase == target_phase:
            self._phase_widget.set_operation_state("idle")
        else:
            phase_text = current_phase if current_phase is not None else "нет активной фазы"
            self._phase_widget.set_operation_state(
                "error",
                f"Engine подтвердил: {phase_text}; запрошенная фаза не применена",
            )
        self._update_mutation_authority()

    # ------------------------------------------------------------------
    # Experiment status forwarding (B.5)
    # ------------------------------------------------------------------

    def on_experiment_status(self, status: dict) -> None:
        """Forward experiment_status response to phase widget."""
        if self._phase_widget is not None:
            self._phase_widget.on_status_update(status)
            if self._phase_context is not None:
                current_id = self._phase_widget.active_experiment_id
                if current_id != self._phase_context.get("experiment_id"):
                    self._phase_context = None
                    self._phase_widget.set_operation_state(
                        "error", "Контекст эксперимента изменился; старая команда больше не действует"
                    )
                elif status.get("current_phase") == self._phase_context.get("phase"):
                    self._phase_context = None
                    self._phase_widget.set_operation_state("idle")
            self._update_mutation_authority()

    # ------------------------------------------------------------------
    # Quick log handlers (B.7)
    # ------------------------------------------------------------------

    def _on_log_entry_submitted(self, message: str) -> None:
        """Persist a quick note with an exact, safely retryable receipt."""
        message = message.strip()
        experiment_id = self._authority_experiment_id
        if (
            self._read_only
            or not self._connected
            or not self._authority_valid
            or (experiment_id is not None and (type(experiment_id) is not str or not experiment_id))
            or not message
        ):
            return
        if self._log_submit_worker is not None:
            return

        if self._log_unresolved_context is not None:
            if message != self._log_unresolved_context.get("message"):
                if self._quick_log is not None:
                    self._quick_log.set_submission_state(
                        "unknown",
                        "Сначала нужно сверить предыдущую запись с неизвестным исходом",
                    )
                return
            self._start_log_submit(self._log_unresolved_context)
            return

        request_id = uuid.uuid4().hex
        author = bounded_operator_log_identity(self._settings.value("last_log_author", ""))
        if author is None:
            if self._quick_log is not None:
                self._quick_log.set_submission_state(
                    "error",
                    "Set a bounded operator identity in the operator journal before using quick log.",
                )
            return
        payload = {
            "cmd": "log_entry",
            "request_id": request_id,
            "message": message,
            "author": author,
            "source": "dashboard",
            "tags": [],
        }
        if experiment_id is None:
            payload["experiment_unbound"] = True
        else:
            payload["experiment_id"] = experiment_id
        self._start_log_submit(
            {
                "payload": payload,
                "request_id": request_id,
                "experiment_id": experiment_id,
                "message": message,
            }
        )

    def _start_log_submit(self, context: dict[str, Any]) -> None:
        if (
            self._read_only
            or not self._connected
            or not self._authority_valid
            or (
                context is not self._log_unresolved_context
                and context.get("experiment_id") != self._authority_experiment_id
            )
            or self._log_submit_worker is not None
        ):
            return
        if not self._persist_unresolved_log(context):
            if self._quick_log is not None:
                self._quick_log.set_submission_state(
                    "error",
                    "The stable retry key could not be persisted; the entry was not sent.",
                )
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        context["attempt_generation"] = self._connection_generation
        worker = ZmqCommandWorker(dict(context["payload"]), parent=self)
        worker.finished.connect(
            lambda result, expected=context, completed_worker=worker: self._on_log_entry_result(
                result, expected, completed_worker
            )
        )
        self._log_submit_context = context
        self._log_submit_worker = worker
        if self._quick_log is not None:
            self._quick_log.set_submission_state(
                "pending",
                "Запись отправлена; ожидается точное подтверждение журнала",
            )
        worker.start()

    @staticmethod
    def _log_commit_receipt_matches(result: object, context: dict[str, Any]) -> bool:
        return operator_log_commit_receipt_matches(result, context)

    def _on_log_entry_result(
        self,
        result: dict,
        context: dict[str, Any] | None = None,
        worker: Any | None = None,
    ) -> None:
        expected = context or self._log_submit_context or self._log_unresolved_context
        if expected is None:
            return
        if worker is not None and worker is not self._log_submit_worker:
            return
        if worker is not None:
            self._log_submit_worker = None
        if self._log_submit_context is expected:
            self._log_submit_context = None
        if not isinstance(result, dict):
            result = {"ok": False, "_unknown": True, "error": "Некорректный ответ Engine"}

        if self._log_commit_receipt_matches(result, expected):
            if self._log_unresolved_context is expected:
                self._log_unresolved_context = None
            self._clear_persisted_unresolved_log()
            if self._quick_log is not None:
                self._quick_log.confirm_submission(str(expected.get("message", "")))
            if self._connected:
                self._poll_log_entries()
            return

        if result.get("committed") is True or _log_result_is_unknown(result):
            self._log_unresolved_context = expected
            if self._quick_log is not None:
                self._quick_log.set_submission_state(
                    "unknown",
                    "Engine не подтвердил, сохранена ли запись; текст сохранён, повтор сверит тот же ключ",
                )
            return

        if self._log_unresolved_context is expected:
            self._log_unresolved_context = None
        self._clear_persisted_unresolved_log()
        if self._quick_log is not None:
            self._quick_log.set_submission_state("error", "Engine proved that the quick-log entry was not committed.")
        raw_error_code = result.get("error_code")
        error_code = raw_error_code if type(raw_error_code) is str and len(raw_error_code) <= 64 else "invalid"
        logger.warning("dashboard log_entry not committed: error_code=%s", error_code)

    def _persist_unresolved_log(self, context: dict[str, Any]) -> bool:
        try:
            encoded = encode_operator_log_unresolved(context)
            self._settings.setValue(_DASHBOARD_UNRESOLVED_SETTINGS_KEY, encoded)
            self._settings.sync()
            return self._settings.status() == QSettings.Status.NoError
        except (TypeError, ValueError):
            return False

    def _clear_persisted_unresolved_log(self) -> None:
        self._settings.remove(_DASHBOARD_UNRESOLVED_SETTINGS_KEY)
        self._settings.sync()

    def _poll_log_entries(self) -> None:
        """Fetch latest log entries for QuickLogBlock."""
        if not self._connected:
            return
        if self._log_poll_worker is not None:
            self._log_poll_pending = True
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        context: dict[str, Any] = {
            "generation": self._connection_generation,
            "log_scope": "all",
            "experiment_id": None,
        }
        worker = ZmqCommandWorker(
            {"cmd": "log_get", "limit": 2, "log_scope": "all"}, parent=self, release_on_settle=True
        )
        worker.finished.connect(
            lambda result, expected=context, completed_worker=worker: self._on_log_entries_received(
                result, expected, completed_worker
            )
        )
        self._log_poll_context = context
        self._log_poll_worker = worker
        worker.start()

    @staticmethod
    def _log_scope_receipt_matches(result: object, context: dict[str, Any]) -> bool:
        if not isinstance(result, dict):
            return False
        receipt = result.get("scope_receipt")
        return (
            isinstance(receipt, dict)
            and receipt.get("schema") == _LOG_READ_SCOPE_SCHEMA
            and receipt.get("log_scope") == context.get("log_scope")
            and receipt.get("experiment_id") == context.get("experiment_id")
        )

    def _on_log_entries_received(
        self,
        result: dict,
        context: dict[str, Any] | None = None,
        worker: Any | None = None,
    ) -> None:
        expected = context or self._log_poll_context
        if worker is not None and worker is not self._log_poll_worker:
            return
        if worker is not None:
            self._log_poll_worker = None
            self._log_poll_context = None
        if expected is None or self._quick_log is None:
            self._finish_log_poll_cycle()
            return
        current_request = self._connected and expected.get("generation") == self._connection_generation
        if not current_request:
            self._finish_log_poll_cycle()
            return
        if not result.get("ok"):
            self._quick_log.set_read_stale(
                f"Журнал не обновлён; показаны последние данные. {result.get('error', '')}".strip()
            )
            self._finish_log_poll_cycle()
            return
        if not self._log_scope_receipt_matches(result, expected):
            self._quick_log.set_read_stale("Engine не подтвердил точную область журнала; показаны последние данные")
            self._finish_log_poll_cycle()
            return
        entries = result.get("entries")
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            self._quick_log.set_read_stale("Engine вернул повреждённый журнал; показаны последние данные")
            self._finish_log_poll_cycle()
            return
        self._quick_log.set_entries(list(entries))
        self._quick_log.set_read_stale(None)
        self._finish_log_poll_cycle()

    def _finish_log_poll_cycle(self) -> None:
        if not self._log_poll_pending:
            return
        self._log_poll_pending = False
        if self._connected:
            QTimer.singleShot(0, self._poll_log_entries)
