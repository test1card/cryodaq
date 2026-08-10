"""Smoke tests for DashboardView skeleton (Phase UI-1 v2 Block B.1)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QFrame, QScrollArea

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.drivers.base import Reading
from cryodaq.gui.dashboard import DashboardView
from cryodaq.gui.dashboard.dashboard_view import _PRESENTATION_INTERVAL_MS
from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION
from cryodaq.operator_snapshot import (
    AttentionQueue,
    AvailabilityTruth,
    CooldownHistorySummary,
    DataIntegritySummary,
    ExperimentOperatingState,
    InfrastructureNode,
    InfrastructureNodeHealth,
    OperatorPresentationState,
    OperatorSnapshot,
    PlantHealthItem,
    PlantHealthSummary,
    ReadinessSummary,
    ReadinessTruth,
    RecordingTruth,
    SafetyLifecycle,
    SnapshotCut,
    SnapshotMode,
    SummaryStatus,
    SupportBundleEntry,
    SupportBundleManifest,
    SupportBundleSummary,
)


@pytest.fixture(autouse=True)
def _gui_worker_root_session(gui_worker_root_epoch):
    """Isolate dashboard settings inside the shared GUI worker root."""

    assert gui_worker_root_epoch is not None
    settings = QSettings("FIAN", "CryoDAQ")
    keys = ("dashboard/unresolved_operator_log_v1", "last_log_author")
    saved = {key: (settings.contains(key), settings.value(key)) for key in keys}
    settings.remove("dashboard/unresolved_operator_log_v1")
    settings.setValue("last_log_author", "operator")
    settings.sync()
    try:
        yield gui_worker_root_epoch
    finally:
        for key, (present, value) in saved.items():
            if present:
                settings.setValue(key, value)
            else:
                settings.remove(key)
        settings.sync()


class _DeferredSignal:
    def __init__(self) -> None:
        self._callback = None

    def connect(self, callback) -> None:  # noqa: ANN001
        self._callback = callback

    def emit(self, result: dict) -> None:
        assert self._callback is not None
        self._callback(result)


class _DeferredWorker:
    instances: list[_DeferredWorker] = []

    def __init__(self, payload: dict, parent=None) -> None:  # noqa: ANN001
        self.payload = dict(payload)
        self.parent = parent
        self.finished = _DeferredSignal()
        self.started = False
        self.done = False
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.started = True

    def finish(self, result: dict) -> None:
        assert self.started and not self.done
        self.done = True
        self.finished.emit(result)


def _install_deferred_worker(monkeypatch) -> None:  # noqa: ANN001
    import cryodaq.gui.zmq_client as zmq_client

    _DeferredWorker.instances.clear()
    monkeypatch.setattr(zmq_client, "ZmqCommandWorker", _DeferredWorker)


def _scope_result(entries: list[dict], *, log_scope: str = "all") -> dict:
    return {
        "ok": True,
        "entries": entries,
        "scope_receipt": {
            "schema": "operator_log_read_scope_v1",
            "log_scope": log_scope,
            "experiment_id": None,
        },
    }


def _settle_connection(view: DashboardView, *, experiment_id: str) -> None:
    view.set_connected(True)
    assert len(_DeferredWorker.instances) == 1
    _DeferredWorker.instances.pop(0).finish(_scope_result([]))
    view.set_operator_snapshot(_operator_snapshot(experiment_id=experiment_id))


def _operator_snapshot(
    *,
    experiment_id: str = "no-active-experiment",
    revision: int = 1,
    producer_id: str = "engine-test",
    lifecycle: SafetyLifecycle = SafetyLifecycle.READY,
    readiness: ReadinessTruth = ReadinessTruth.READY,
    mode: SnapshotMode = SnapshotMode.LIVE,
) -> OperatorSnapshot:
    observed = datetime.now(UTC)
    cut = SnapshotCut(revision, observed, observed, producer_id, mode, experiment_id, producer_id)
    presentation = (
        OperatorPresentationState.OK
        if mode is SnapshotMode.LIVE and readiness is ReadinessTruth.READY and lifecycle is SafetyLifecycle.READY
        else OperatorPresentationState.CAUTION
    )
    status = SummaryStatus(presentation, 0.0, 0.0, ("authoritative",), "confirmed")
    manifest = (
        SupportBundleManifest(
            "bundle-1",
            cut.received_at,
            (SupportBundleEntry("status/status.json", 1, "a" * 64),),
        )
        if mode is SnapshotMode.LIVE
        else None
    )
    availability = AvailabilityTruth.AVAILABLE if mode is SnapshotMode.LIVE else AvailabilityTruth.UNKNOWN
    recording = RecordingTruth.NOT_RECORDING if mode is SnapshotMode.LIVE else RecordingTruth.REPLAY_ONLY
    active_experiment = None if experiment_id == "no-active-experiment" else experiment_id
    return OperatorSnapshot(
        cut,
        ReadinessSummary(cut, status, readiness, (), lifecycle),
        PlantHealthSummary(
            cut,
            status,
            (PlantHealthItem("plant", "Plant", presentation, ()),),
        ),
        InfrastructureNodeHealth(
            cut,
            status,
            (InfrastructureNode("engine", "Engine", presentation, ()),),
        ),
        AttentionQueue(cut, status, ()),
        ExperimentOperatingState(
            cut,
            status,
            active_experiment,
            "Experiment" if active_experiment else None,
            "cooldown" if active_experiment else None,
            recording,
            None,
        ),
        DataIntegritySummary(cut, status, revision, revision, 0, 0, availability),
        CooldownHistorySummary(cut, status, (), None, ()),
        SupportBundleSummary(cut, status, availability, manifest),
    )


def _commit_result(context: dict, *, entry_id: int = 1) -> dict:
    payload = context["payload"]
    entry = {
        "id": entry_id,
        "timestamp": "2026-07-19T08:00:00+00:00",
        "message": context["message"],
        "experiment_id": context["experiment_id"],
        "author": payload["author"],
        "source": payload["source"],
        "tags": list(payload["tags"]),
    }
    return {
        "ok": True,
        "committed": True,
        "retry_safe": False,
        "publication_state": "published",
        "proto": CLIENT_PROTOCOL_VERSION,
        "entry": entry,
        "commit_receipt": {
            "schema": "operator_log_commit_v1",
            "request_id": context["request_id"],
            "entry_id": entry_id,
            "experiment_id": context["experiment_id"],
            "committed": True,
        },
    }


def _phase_commit_result(context: dict) -> dict:
    return {
        "ok": True,
        "committed": True,
        "experiment_id": context["experiment_id"],
        "phase": {"phase": context["phase"], "started_at": "2026-07-19T08:00:00+00:00"},
        "commit_receipt": {
            "schema": "experiment_command_commit_v1",
            "action": "experiment_advance_phase",
            "experiment_id": context["experiment_id"],
            "manager_revision": 8,
            "committed": True,
        },
    }


@pytest.fixture(scope="module")
def app():
    qapp = QApplication.instance() or QApplication([])
    yield qapp


def test_dashboard_view_constructs(app):
    """DashboardView instantiates without error."""
    mgr = ChannelManager()
    view = DashboardView(mgr)
    assert view is not None


def test_dashboard_restores_unresolved_quick_log_with_russian_operator_text(app):
    """Guard for the Russian-operator-wording gate (AGENTS.md GUI design-system gate).

    The constructor-time restore of a disk-persisted unresolved quick-log entry
    must present the same Russian wording as every other quick-log/operator-log
    "outcome unknown" surface, not an English string.
    """

    from cryodaq.gui.shell.overlays.operator_log_panel import encode_operator_log_unresolved

    request_id = "0" * 32
    payload = {
        "cmd": "log_entry",
        "request_id": request_id,
        "message": "тестовая запись",
        "author": "operator",
        "source": "dashboard",
        "tags": [],
        "experiment_unbound": True,
    }
    context = {
        "payload": payload,
        "request_id": request_id,
        "experiment_id": None,
        "message": "тестовая запись",
    }
    encoded = encode_operator_log_unresolved(context)
    settings = QSettings("FIAN", "CryoDAQ")
    settings.setValue("dashboard/unresolved_operator_log_v1", encoded)
    settings.sync()

    view = DashboardView(ChannelManager())

    assert view._log_unresolved_context is not None
    detail = view._quick_log._submission_detail
    assert detail == "Найдена незавершённая запись. Текст сохранён, повтор сверит тот же ключ."
    assert not detail.isascii(), "restored unresolved-log detail must be Russian, not English"


def test_dashboard_connection_contract_disables_mutations_until_live_and_after_loss(app):
    view = DashboardView(ChannelManager())

    assert not view._connected
    assert not view._phase_widget._create_btn.isEnabled()
    assert not view._quick_log._send_btn.isEnabled()
    assert view._sensor_grid._read_only is True

    view.set_connected(True)
    assert view._sensor_grid._read_only is True
    view.set_operator_snapshot(_operator_snapshot())
    assert view._phase_widget._create_btn.isEnabled()
    assert view._quick_log._send_btn.isEnabled()
    assert view._sensor_grid._read_only is False

    view.set_connected(False)
    assert not view._phase_widget._create_btn.isEnabled()
    assert not view._quick_log._send_btn.isEnabled()
    assert view._sensor_grid._read_only is True


def test_authority_receipt_requires_explicit_lifecycle_and_exact_identity(app):
    view = DashboardView(ChannelManager())
    view.set_connected(True)
    view.set_operator_snapshot(
        {
            "experiment_id": "exp-1",
            "producer_id": "engine-test",
            "revision": 1,
            "readiness": ReadinessTruth.READY,
        }
    )
    assert view._authority_valid is False
    assert not view._phase_widget._create_btn.isEnabled()
    assert not view._quick_log._send_btn.isEnabled()
    assert view._sensor_grid._read_only is True

    ready = _operator_snapshot(experiment_id="exp-1", revision=1)
    view.set_operator_snapshot(ready)
    assert view._authority_valid is True
    assert view._authority_experiment_id == "exp-1"
    assert view._authority_producer_id == "engine-test"
    assert view._sensor_grid._read_only is False
    view.set_operator_snapshot(ready)
    assert view._authority_valid is True

    # A different coherent snapshot at the same revision is equivocation, even
    # when both snapshots claim READY.
    view.set_operator_snapshot(_operator_snapshot(experiment_id="exp-1", revision=1))
    assert view._authority_valid is False
    assert view._sensor_grid._read_only is True

    # An equivocal equal-revision delivery revokes the previously optimistic
    # cut, and the original READY object cannot replay that authority.
    view.set_operator_snapshot(
        _operator_snapshot(
            experiment_id="exp-1",
            revision=1,
            lifecycle=SafetyLifecycle.UNKNOWN,
            readiness=ReadinessTruth.UNKNOWN,
        )
    )
    view.set_operator_snapshot(ready)
    assert view._authority_valid is False
    assert view._authority_revision == 1

    view.set_operator_snapshot(_operator_snapshot(experiment_id="exp-1", revision=2))
    assert view._authority_valid is True
    assert view._sensor_grid._read_only is False

    view.set_operator_snapshot(
        _operator_snapshot(
            experiment_id="exp-1",
            revision=3,
            lifecycle=SafetyLifecycle.UNKNOWN,
            readiness=ReadinessTruth.UNKNOWN,
        )
    )
    assert view._authority_valid is False
    assert view._authority_revision == 3
    assert view._authority_producer_id == "engine-test"
    assert view._sensor_grid._read_only is True

    # An older READY cut and a READY-looking producer replacement cannot
    # restore authority after revocation. A real reconnect is required for a
    # producer/incarnation replacement.
    view.set_operator_snapshot(ready)
    view.set_operator_snapshot(_operator_snapshot(experiment_id="exp-1", revision=4, producer_id="engine-other"))
    assert view._authority_valid is False
    assert not view._phase_widget._create_btn.isEnabled()
    assert not view._quick_log._send_btn.isEnabled()

    view.set_connected(False)
    assert view._authority_producer_id is None
    assert view._authority_revision is None
    assert view._sensor_grid._read_only is True


def test_explicit_producer_retirement_allows_fast_successor_without_silence_timeout(app):
    view = DashboardView(ChannelManager())
    view.set_connected(True)
    view.set_operator_snapshot(
        _operator_snapshot(
            experiment_id="exp-a",
            revision=42,
            producer_id="engine-a",
        )
    )
    assert view._authority_valid is True
    initial_generation = view._connection_generation

    view.invalidate_operator_snapshot_producer()

    assert view._connected is False
    assert view._connection_generation == initial_generation + 1
    assert view._authority_valid is False
    assert view._authority_producer_id is None
    assert view._authority_revision is None
    assert view._sensor_grid._read_only is True

    view.set_connected(True)
    view.set_operator_snapshot(
        _operator_snapshot(
            experiment_id="exp-b",
            revision=1,
            producer_id="engine-b",
        )
    )
    assert view._authority_valid is True
    assert view._authority_producer_id == "engine-b"
    assert view._authority_revision == 1
    assert view._sensor_grid._read_only is False


def test_dashboard_replay_cut_advances_highwater_and_cannot_restore_live_authority(app):
    view = DashboardView(ChannelManager())
    view.set_connected(True)
    view.set_operator_snapshot(_operator_snapshot(experiment_id="exp-1", revision=42))
    assert view._authority_valid is True

    view.set_operator_snapshot(
        _operator_snapshot(
            experiment_id="exp-1",
            revision=50,
            lifecycle=SafetyLifecycle.UNKNOWN,
            readiness=ReadinessTruth.UNKNOWN,
            mode=SnapshotMode.REPLAY,
        )
    )
    assert view._authority_valid is False
    assert view._authority_revision == 50

    view.set_operator_snapshot(_operator_snapshot(experiment_id="exp-1", revision=43))
    assert view._authority_valid is False
    assert view._authority_revision == 50


def test_telemetry_does_not_enable_mutations(app):
    view = DashboardView(ChannelManager())
    view.set_connected(True)
    view.on_reading(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="safety_manager",
            channel="analytics/safety_state",
            value=0.0,
            unit="",
            metadata={
                "state": "ready",
                "lifecycle": "ready",
                "readiness": "ready",
                "experiment_id": "exp-telemetry",
                "producer_id": "engine-telemetry",
                "revision": 999,
            },
        )
    )
    assert view._authority_valid is False
    assert view._authority_experiment_id is None
    assert view._authority_revision is None
    assert not view._phase_widget._create_btn.isEnabled()
    assert not view._quick_log._send_btn.isEnabled()


def test_dashboard_presentation_tick_is_bounded_to_two_hz(app):
    mgr = ChannelManager()
    view = DashboardView(mgr)

    assert _PRESENTATION_INTERVAL_MS == 500
    assert view._refresh_timer.interval() == _PRESENTATION_INTERVAL_MS


def test_dashboard_view_has_five_zones(app):
    """All five placeholder zones are present with expected object names."""
    mgr = ChannelManager()
    view = DashboardView(mgr)
    expected = {"phaseZone", "tempPlotZone", "pressurePlotZone", "sensorGridZone", "quickLogZone"}
    actual = {c.objectName() for c in view.findChildren(QFrame) if c.objectName() in expected}
    assert expected == actual, f"Missing: {expected - actual}"


def test_dashboard_scrolls_vertically_without_horizontal_clipping_or_sensor_hiding(app):
    mgr = ChannelManager()
    mgr._channels = {f"Т{index}": {"name": f"Датчик {index}", "visible": True} for index in range(1, 13)}
    view = DashboardView(mgr)
    view.resize(720, 360)
    view.show()
    app.processEvents()

    assert isinstance(view, QScrollArea)
    assert view.accessibleName() == "Панель мониторинга"
    assert view.focusPolicy() is Qt.FocusPolicy.StrongFocus
    assert view.horizontalScrollBarPolicy() is Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert view.horizontalScrollBar().maximum() == 0
    assert view.verticalScrollBar().maximum() > 0
    assert tuple(view._sensor_grid._cells) == tuple(f"Т{index}" for index in range(1, 13))
    assert view._sensor_grid._grid_layout.count() == 12
    assert view._sensor_grid.height() >= view._sensor_grid.minimumSizeHint().height()
    assert view._sensor_grid._grid_widget.geometry().bottom() <= view._sensor_grid.contentsRect().bottom()


def test_dashboard_view_on_reading_accepts(app):
    """on_reading() accepts a reading without raising."""
    from datetime import datetime

    from cryodaq.drivers.base import ChannelStatus, Reading

    mgr = ChannelManager()
    view = DashboardView(mgr)
    reading = Reading(
        channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
        value=4.2,
        unit="K",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    view.on_reading(reading)  # should not raise


def test_on_reading_temperature_stores_short_id(app):
    """Temperature reading stored under short ID (Т1) in buffer."""
    from datetime import datetime

    from cryodaq.drivers.base import ChannelStatus, Reading

    mgr = ChannelManager()
    view = DashboardView(mgr)
    reading = Reading(
        channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
        value=77.5,
        unit="K",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    view.on_reading(reading)
    last = view._buffer_store.get_last("\u04221")
    assert last is not None
    assert last[1] == 77.5


def test_dashboard_disconnect_keeps_sensor_value_explicitly_last_known_until_new_sample(app):
    """Disconnect quarantines raw measurement presentation until new evidence."""
    from cryodaq.drivers.base import ChannelStatus
    from cryodaq.gui import theme
    from cryodaq.gui.state.descriptor_store import IdentityStatus

    manager = ChannelManager()
    view = DashboardView(manager)
    view.set_connected(True)
    view.on_reading(
        Reading(
            channel="Т1 Криостат верх",
            value=4.2,
            unit="K",
            timestamp=datetime.now(UTC),
            status=ChannelStatus.OK,
            instrument_id="lakeshore_218s",
        ),
        IdentityStatus.AUTHORITATIVE,
    )
    view.on_reading(
        Reading(
            channel="vacuum/pressure",
            value=1.2e-5,
            unit="mbar",
            timestamp=datetime.now(UTC),
            status=ChannelStatus.OK,
            instrument_id="vacuum_gauge",
        ),
        IdentityStatus.AUTHORITATIVE,
    )
    view._sensor_grid.refresh()
    cell = view._sensor_grid._cells["Т1"]
    assert cell._status_hint_widget.text() == "Норма"
    accepted_temperature = view._buffer_store.get_last("Т1")
    accepted_pressure = view._buffer_store.get_last("vacuum/pressure")
    assert accepted_temperature is not None
    assert accepted_pressure is not None
    assert view._temp_plot._buffer is view._buffer_store
    assert view._pressure_plot._buffer is view._buffer_store

    view.set_connected(False)

    assert cell._value_widget.text() == "4.20"
    assert cell._status_hint_widget.text() == "Нет связи · последнее известное значение"
    assert "dashed" in cell.styleSheet()
    assert theme.TEXT_DISABLED in cell._value_widget.styleSheet()

    manager._notify()
    rebuilt_cell = view._sensor_grid._cells["Т1"]
    assert rebuilt_cell is not cell
    view._sensor_grid.refresh()
    assert rebuilt_cell._value_widget.text() == "4.20"
    assert rebuilt_cell._status_hint_widget.text() == "Нет связи · последнее известное значение"
    assert "dashed" in rebuilt_cell.styleSheet()
    assert theme.TEXT_DISABLED in rebuilt_cell._value_widget.styleSheet()

    view.on_reading(
        Reading(
            channel="Т1 Криостат верх",
            value=3.9,
            unit="K",
            timestamp=datetime.now(UTC),
            status=ChannelStatus.OK,
            instrument_id="lakeshore_218s",
        ),
        IdentityStatus.AUTHORITATIVE,
    )
    view.on_reading(
        Reading(
            channel="vacuum/pressure",
            value=9.9e-4,
            unit="mbar",
            timestamp=datetime.now(UTC),
            status=ChannelStatus.OK,
            instrument_id="vacuum_gauge",
        ),
        IdentityStatus.AUTHORITATIVE,
    )
    view._sensor_grid.refresh()
    assert rebuilt_cell._value_widget.text() == "4.20"
    assert rebuilt_cell._status_hint_widget.text() == "Нет связи · последнее известное значение"
    assert "dashed" in rebuilt_cell.styleSheet()
    assert theme.TEXT_DISABLED in rebuilt_cell._value_widget.styleSheet()
    assert view._buffer_store.get_last("Т1") == accepted_temperature
    assert view._buffer_store.get_last("vacuum/pressure") == accepted_pressure

    view.set_connected(True)
    view._sensor_grid.refresh()
    assert rebuilt_cell._status_hint_widget.text() == "Нет связи · последнее известное значение"
    assert "dashed" in rebuilt_cell.styleSheet()
    assert theme.TEXT_DISABLED in rebuilt_cell._value_widget.styleSheet()

    view.on_reading(
        Reading(
            channel="Т1 Криостат верх",
            value=4.1,
            unit="K",
            timestamp=datetime.now(UTC),
            status=ChannelStatus.OK,
            instrument_id="lakeshore_218s",
        ),
        IdentityStatus.AUTHORITATIVE,
    )
    view._sensor_grid.refresh()

    assert rebuilt_cell._value_widget.text() == "4.10"
    assert rebuilt_cell._status_hint_widget.text() == "Норма"
    assert "dashed" not in rebuilt_cell.styleSheet()
    assert theme.TEXT_DISABLED not in rebuilt_cell._value_widget.styleSheet()


def test_dashboard_disconnect_preserves_last_interval_fault_as_historical_evidence(app):
    """Connectivity loss keeps abnormal backend evidence, explicitly historical."""
    from cryodaq.drivers.base import ChannelStatus
    from cryodaq.gui import theme
    from cryodaq.gui.state.descriptor_store import IdentityStatus

    manager = ChannelManager()
    view = DashboardView(manager)
    for value, status in (
        (77.0, ChannelStatus.OK),
        (500.0, ChannelStatus.OVERRANGE),
        (78.0, ChannelStatus.OK),
    ):
        view.on_reading(
            Reading.now(
                channel="Т1",
                value=value,
                unit="K",
                instrument_id="lakeshore_218s",
                status=status,
            ),
            IdentityStatus.AUTHORITATIVE,
        )
    view._sensor_grid.refresh()
    cell = view._sensor_grid._cells["Т1"]
    assert cell._status_hint_widget.text() == "Перегрузка (за интервал)"

    view.set_connected(False)

    def assert_historical_fault(rendered_cell) -> None:
        text = rendered_cell._status_hint_widget.text()
        assert rendered_cell._value_widget.text() == "78.00"
        assert "Нет связи" in text
        assert "последний принятый статус: Перегрузка" in text
        assert "Норма" not in text
        assert rendered_cell.accessibleDescription() == text
        assert "dashed" in rendered_cell.styleSheet()
        assert f"border-left: 4px solid {theme.STATUS_FAULT}" in rendered_cell.styleSheet()
        assert theme.TEXT_DISABLED in rendered_cell._value_widget.styleSheet()

    assert_historical_fault(cell)

    manager._notify()
    rebuilt_cell = view._sensor_grid._cells["Т1"]
    assert rebuilt_cell is not cell
    assert_historical_fault(rebuilt_cell)

    view.set_connected(True)
    assert_historical_fault(rebuilt_cell)

    view.on_reading(
        Reading.now(
            channel="Т1",
            value=79.0,
            unit="K",
            instrument_id="lakeshore_218s",
            status=ChannelStatus.OK,
        ),
        IdentityStatus.AUTHORITATIVE,
    )
    view._sensor_grid.refresh()

    assert rebuilt_cell._value_widget.text() == "79.00"
    assert rebuilt_cell._status_hint_widget.text() == "Норма"
    assert "dashed" not in rebuilt_cell.styleSheet()
    assert "последний" not in rebuilt_cell.accessibleDescription().lower()


def test_dashboard_disconnect_preserves_refused_identity_across_rebuild(app):
    """A refused descriptor remains visible as historical evidence offline."""
    from cryodaq.drivers.base import ChannelStatus
    from cryodaq.gui.state.descriptor_store import IdentityStatus

    manager = ChannelManager()
    view = DashboardView(manager)
    view.on_reading(
        Reading.now(
            channel="Т1",
            value=4.2,
            unit="K",
            instrument_id="lakeshore_218s",
            status=ChannelStatus.OK,
        ),
        IdentityStatus.REFUSED,
    )
    view._sensor_grid.refresh()
    view.set_connected(False)

    def assert_historical_refusal(rendered_cell) -> None:
        text = rendered_cell._status_hint_widget.text()
        assert "Нет связи" in text
        assert "последняя идентификация: описание канала отклонено" in text
        assert "Норма" not in text
        assert rendered_cell.accessibleDescription() == text
        assert "dashed" in rendered_cell.styleSheet()

    cell = view._sensor_grid._cells["Т1"]
    assert_historical_refusal(cell)
    assert "Нет связи" in view._sensor_grid._identity_banner.text()
    assert "последняя идентификация" in view._sensor_grid._identity_banner.text().lower()
    assert view._sensor_grid._identity_banner.accessibleName() == view._sensor_grid._identity_banner.text()

    manager._notify()
    rebuilt_cell = view._sensor_grid._cells["Т1"]
    assert rebuilt_cell is not cell
    assert_historical_refusal(rebuilt_cell)
    assert "Нет связи" in view._sensor_grid._identity_banner.text()
    assert "последняя идентификация" in view._sensor_grid._identity_banner.text().lower()

    view.set_connected(True)
    assert_historical_refusal(rebuilt_cell)

    view.on_reading(
        Reading.now(
            channel="Т1",
            value=4.1,
            unit="K",
            instrument_id="lakeshore_218s",
            status=ChannelStatus.OK,
        ),
        IdentityStatus.AUTHORITATIVE,
    )
    view._sensor_grid.refresh()

    assert rebuilt_cell._status_hint_widget.text() == "Норма"
    assert not view._sensor_grid._identity_banner.isVisible()


def test_dashboard_first_explicit_disconnect_rejects_cold_start_reading(app):
    """The production shell's initial False call establishes a closed generation."""
    from cryodaq.drivers.base import ChannelStatus
    from cryodaq.gui.state.descriptor_store import IdentityStatus

    view = DashboardView(ChannelManager())
    view.set_connected(False)
    assert view._connection_generation == 1

    view.on_reading(
        Reading(
            channel="Т1 Криостат верх",
            value=8.8,
            unit="K",
            timestamp=datetime.now(UTC),
            status=ChannelStatus.OK,
            instrument_id="lakeshore_218s",
        ),
        IdentityStatus.AUTHORITATIVE,
    )
    view._sensor_grid.refresh()

    cell = view._sensor_grid._cells["Т1"]
    assert view._buffer_store.get_last("Т1") is None
    assert cell._value_widget.text() == "—"
    assert cell._status_hint_widget.text() == "Нет связи · данных нет"
    assert "dashed" in cell.styleSheet()


def test_dashboard_producer_retirement_invalidates_gen_zero_startup_evidence(app):
    """Explicit producer turnover revokes even pre-status startup evidence."""
    from cryodaq.drivers.base import ChannelStatus
    from cryodaq.gui.state.descriptor_store import IdentityStatus

    view = DashboardView(ChannelManager())
    view.on_reading(
        Reading(
            channel="Т1 Криостат верх",
            value=6.6,
            unit="K",
            timestamp=datetime.now(UTC),
            status=ChannelStatus.OK,
            instrument_id="lakeshore_218s",
        ),
        IdentityStatus.AUTHORITATIVE,
    )
    view._sensor_grid.refresh()
    cell = view._sensor_grid._cells["Т1"]
    accepted = view._buffer_store.get_last("Т1")
    assert cell._status_hint_widget.text() == "Норма"
    assert accepted is not None

    view.invalidate_operator_snapshot_producer()

    assert view._connection_generation == 1
    assert cell._value_widget.text() == "6.60"
    assert cell._status_hint_widget.text() == "Нет связи · последнее известное значение"
    assert "dashed" in cell.styleSheet()

    view.on_reading(
        Reading(
            channel="Т1 Криостат верх",
            value=7.7,
            unit="K",
            timestamp=datetime.now(UTC),
            status=ChannelStatus.OK,
            instrument_id="lakeshore_218s",
        ),
        IdentityStatus.AUTHORITATIVE,
    )
    view._sensor_grid.refresh()
    assert view._buffer_store.get_last("Т1") == accepted
    assert cell._value_widget.text() == "6.60"
    assert cell._status_hint_widget.text() == "Нет связи · последнее известное значение"


def test_dashboard_disconnect_revokes_mutations_before_passive_rendering(app, monkeypatch):
    """A sensor-rendering failure cannot retain mutation authority."""
    view = DashboardView(ChannelManager())
    view.set_connected(True)
    view.set_operator_snapshot(_operator_snapshot(experiment_id="exp-1", revision=1))
    assert view._phase_widget._create_btn.isEnabled()
    assert view._quick_log._send_btn.isEnabled()

    def fail_passive_rendering() -> None:
        raise RuntimeError("sensor rendering failed")

    monkeypatch.setattr(view._sensor_grid, "invalidate_transport", fail_passive_rendering)
    with pytest.raises(RuntimeError, match="sensor rendering failed"):
        view.set_connected(False)

    assert view._connected is False
    assert view._authority_valid is False
    assert not view._phase_widget._create_btn.isEnabled()
    assert not view._quick_log._send_btn.isEnabled()
    assert view._sensor_grid._read_only is True


def test_coalescing_preserves_every_sample_in_full_rate_buffer(app):
    from datetime import datetime

    from cryodaq.drivers.base import ChannelStatus, Reading
    from cryodaq.gui.state.descriptor_store import IdentityStatus

    mgr = ChannelManager()
    view = DashboardView(mgr)
    for value, status in (
        (77.0, ChannelStatus.OK),
        (500.0, ChannelStatus.OVERRANGE),
        (78.0, ChannelStatus.OK),
    ):
        view.on_reading(
            Reading(
                channel="\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442 \u0432\u0435\u0440\u0445",
                value=value,
                unit="K",
                timestamp=datetime.now(UTC),
                status=status,
                instrument_id="lakeshore_218s",
            ),
            IdentityStatus.AUTHORITATIVE,
        )

    assert [value for _, value in view._buffer_store.get_history("\u04221")] == [
        77.0,
        500.0,
        78.0,
    ]
    assert view._sensor_grid is not None
    pending = view._sensor_grid._pending_readings["\u04221"]
    assert pending.count == 3
    assert pending.minimum[0].value == 77.0
    assert pending.maximum[0].value == 500.0
    assert pending.last[0].value == 78.0
    assert pending.status_evidence[0].status is ChannelStatus.OVERRANGE

    view._refresh_plots()

    assert view._temp_plot is not None
    plotted = view._temp_plot._plot_items["\u04221"]
    assert list(plotted.yData) == [77.0, 500.0, 78.0]
    cell = view._sensor_grid._cells["\u04221"]
    assert cell._value_widget.text() == "78.00"
    assert cell._status_hint_widget.text() == "Перегрузка (за интервал)"

    view._sensor_grid.refresh()

    assert cell._status_hint_widget.text() == "Норма"


def test_on_reading_pressure_stores_full_id(app):
    """Pressure reading stored under full channel ID."""
    from datetime import datetime

    from cryodaq.drivers.base import ChannelStatus, Reading

    mgr = ChannelManager()
    view = DashboardView(mgr)
    reading = Reading(
        channel="VSP63D_1/pressure",
        value=1e-4,
        unit="mbar",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="thyracont_vsp63d",
    )
    view.on_reading(reading)
    last = view._buffer_store.get_last("VSP63D_1/pressure")
    assert last is not None
    assert last[1] == 1e-4


def test_dashboard_replay_direct_config_signals_fail_closed(app, monkeypatch):
    """Queued/direct grid signals cannot rename or hide channels in replay."""
    mgr = ChannelManager()
    mgr._channels = {"Т1": {"name": "Исходное", "visible": True}}
    saved: list[bool] = []
    monkeypatch.setattr(mgr, "save", lambda: saved.append(True))
    view = DashboardView(mgr)
    view.set_read_only(True)

    view._sensor_grid.rename_requested.emit("Т1", "Запрещено")
    view._sensor_grid.hide_requested.emit("Т1")
    app.processEvents()

    assert mgr.get_name("Т1") == "Исходное"
    assert mgr.is_visible("Т1") is True
    assert saved == []


def test_dashboard_live_config_signals_still_persist(app, monkeypatch):
    """The replay gate does not regress the live rename/hide contract."""
    mgr = ChannelManager()
    mgr._channels = {"Т1": {"name": "Исходное", "visible": True}}
    saved: list[bool] = []
    monkeypatch.setattr(mgr, "save", lambda: saved.append(True))
    view = DashboardView(mgr)
    view.set_connected(True)
    view.set_operator_snapshot(_operator_snapshot())

    view._sensor_grid.rename_requested.emit("Т1", "Новое")
    view._sensor_grid.hide_requested.emit("Т1")
    app.processEvents()

    assert mgr.get_name("Т1") == "Новое"
    assert mgr.is_visible("Т1") is False
    assert saved == [True, True]


def test_dashboard_connected_without_authority_cannot_hide_or_save(app, monkeypatch):
    """Transport connectivity alone cannot authorize persisted configuration changes."""
    mgr = ChannelManager()
    mgr._channels = {"T1": {"name": "Original", "visible": True}}
    saved: list[bool] = []
    monkeypatch.setattr(mgr, "save", lambda: saved.append(True))
    view = DashboardView(mgr)
    view.set_connected(True)

    view._sensor_grid.hide_requested.emit("T1")
    app.processEvents()

    assert view._connected is True
    assert view._authority_valid is False
    assert mgr.is_visible("T1") is True
    assert saved == []


def test_dashboard_quick_log_is_fail_closed_while_disconnected(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    assert view._quick_log is not None
    view._quick_log._input.setText("Не отправлять без Engine")

    view._quick_log._on_submit()
    view._on_log_entry_submitted("Прямой вызов тоже запрещён")

    assert _DeferredWorker.instances == []
    assert view._quick_log._input.text() == "Не отправлять без Engine"
    assert not view._quick_log._send_btn.isEnabled()


def test_dashboard_quick_log_requires_exact_commit_receipt(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    _settle_connection(view, experiment_id="exp-log")
    assert view._quick_log is not None
    view._quick_log._input.setText("Проверить persistence-first")

    view._quick_log._on_submit()

    assert len(_DeferredWorker.instances) == 1
    worker = _DeferredWorker.instances.pop(0)
    context = view._log_submit_context
    assert context is not None
    assert worker.payload == context["payload"]
    assert worker.payload["cmd"] == "log_entry"
    assert worker.payload["experiment_id"] == "exp-log"
    assert worker.payload["author"] == "operator"
    assert "experiment_unbound" not in worker.payload
    assert len(worker.payload["request_id"]) == 32
    assert view._quick_log._input.text() == "Проверить persistence-first"

    worker.finish(_commit_result(context, entry_id=42))

    assert view._quick_log._input.text() == ""
    assert view._quick_log._submission_state == "idle"
    assert len(_DeferredWorker.instances) == 1
    assert _DeferredWorker.instances[0].payload == {
        "cmd": "log_get",
        "limit": 2,
        "log_scope": "all",
    }


def test_dashboard_quick_log_unknown_retries_identical_payload(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    _settle_connection(view, experiment_id="exp-log")
    assert view._quick_log is not None
    view._quick_log._input.setText("Не дублировать при таймауте")
    view._quick_log._on_submit()
    first = _DeferredWorker.instances.pop(0)
    first_payload = dict(first.payload)

    first.finish({"ok": False, "error": "timeout", "_handler_timeout": True})

    assert view._quick_log._submission_state == "unknown"
    assert view._quick_log._input.text() == "Не дублировать при таймауте"
    assert view._log_unresolved_context is not None

    view._quick_log._on_submit()

    assert len(_DeferredWorker.instances) == 1
    retry = _DeferredWorker.instances.pop(0)
    assert retry.payload == first_payload
    retry.finish(_commit_result(view._log_unresolved_context, entry_id=43))
    assert view._quick_log._input.text() == ""


def test_dashboard_quick_log_forged_receipt_keeps_draft_unknown(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    _settle_connection(view, experiment_id="exp-log")
    assert view._quick_log is not None
    view._quick_log._input.setText("Не доверять чужому receipt")
    view._quick_log._on_submit()
    worker = _DeferredWorker.instances.pop(0)
    context = view._log_submit_context
    assert context is not None
    result = _commit_result(context, entry_id=44)
    result["commit_receipt"]["request_id"] = "f" * 32

    worker.finish(result)

    assert view._quick_log._input.text() == "Не доверять чужому receipt"
    assert view._quick_log._submission_state == "unknown"
    assert view._log_unresolved_context is context


@pytest.mark.parametrize(
    ("field", "forged"),
    [
        ("message", "forged message"),
        ("experiment_id", "other-experiment"),
        ("author", "other-author"),
        ("source", "other-source"),
        ("tags", ["forged"]),
    ],
)
def test_dashboard_quick_log_receipt_binds_complete_submitted_payload(
    app,
    monkeypatch,
    field,
    forged,
):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    _settle_connection(view, experiment_id="exp-log")
    assert view._quick_log is not None
    draft = "Bind every persisted field"
    view._quick_log._input.setText(draft)
    view._quick_log._on_submit()
    worker = _DeferredWorker.instances.pop(0)
    context = view._log_submit_context
    assert context is not None
    result = _commit_result(context, entry_id=46)
    result["entry"][field] = forged

    worker.finish(result)

    assert view._quick_log._input.text() == draft
    assert view._quick_log._submission_state == "unknown"
    assert view._log_unresolved_context is context


def test_dashboard_admission_invalid_is_known_uncommitted() -> None:
    from cryodaq.gui.dashboard.dashboard_view import _log_result_is_unknown

    assert (
        _log_result_is_unknown(
            {
                "ok": False,
                "committed": False,
                "error_code": "operator_log_admission_invalid",
                "retry_safe": True,
            }
        )
        is False
    )


@pytest.mark.parametrize(
    ("entry_id", "timestamp"),
    [
        (True, "2026-07-19T08:00:00+00:00"),
        (1.0, "2026-07-19T08:00:00+00:00"),
        (1, "not-an-iso-timestamp"),
    ],
)
def test_dashboard_rejects_type_confused_or_malformed_commit_evidence(entry_id, timestamp) -> None:
    context = {
        "request_id": "a" * 32,
        "experiment_id": "exp-log",
        "message": "exact message",
        "payload": {
            "author": "operator",
            "source": "gui",
            "tags": [],
        },
    }
    result = _commit_result(context, entry_id=entry_id)
    result["entry"]["timestamp"] = timestamp

    assert DashboardView._log_commit_receipt_matches(result, context) is False


@pytest.mark.parametrize("proto", [None, True, CLIENT_PROTOCOL_VERSION + 1, "2"])
def test_dashboard_rejects_missing_or_type_confused_transport_protocol(proto: object) -> None:
    context = {
        "request_id": "a" * 32,
        "experiment_id": "exp-log",
        "message": "exact message",
        "payload": {"author": "operator", "source": "gui", "tags": []},
    }
    result = _commit_result(context)
    if proto is None:
        result.pop("proto")
    else:
        result["proto"] = proto

    assert DashboardView._log_commit_receipt_matches(result, context) is False


def test_dashboard_rejects_extra_transport_success_field() -> None:
    context = {
        "request_id": "a" * 32,
        "experiment_id": "exp-log",
        "message": "exact message",
        "payload": {"author": "operator", "source": "gui", "tags": []},
    }
    result = _commit_result(context)
    result["unexpected"] = True

    assert DashboardView._log_commit_receipt_matches(result, context) is False


def test_dashboard_quick_log_accepts_exact_late_receipt_after_disconnect(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    _settle_connection(view, experiment_id="exp-log")
    assert view._quick_log is not None
    view._quick_log._input.setText("Поздний точный receipt")
    view._quick_log._on_submit()
    worker = _DeferredWorker.instances.pop(0)
    context = view._log_submit_context
    assert context is not None

    view.set_connected(False)
    worker.finish(_commit_result(context, entry_id=45))

    assert view._quick_log._input.text() == ""
    assert view._log_unresolved_context is None
    assert _DeferredWorker.instances == []


def test_dashboard_quick_log_poll_requires_exact_global_scope_and_retains_last_good(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    view.set_connected(True)
    first = _DeferredWorker.instances.pop(0)
    first.finish(_scope_result([{"id": 50, "timestamp": "2026-07-19T08:00:00+00:00", "message": "Последнее"}]))
    view.set_operator_snapshot(_operator_snapshot(experiment_id="exp-log"))
    assert view._quick_log is not None
    assert "Последнее" in view._quick_log._entry_labels[0].text()

    view._poll_log_entries()
    wrong = _DeferredWorker.instances.pop(0)
    result = _scope_result(
        [{"id": 51, "timestamp": "2026-07-19T08:01:00+00:00", "message": "Чужое"}],
        log_scope="experiment",
    )
    wrong.finish(result)

    assert "Последнее" in view._quick_log._entry_labels[0].text()
    assert "Чужое" not in view._quick_log._entry_labels[0].text()
    assert view._quick_log._status_label.text() == "ЖУРНАЛ НЕ ОБНОВЛЁН"


def test_dashboard_no_active_experiment_submits_explicit_unbound_log(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    view.set_connected(True)
    _DeferredWorker.instances.pop(0).finish(_scope_result([]))
    view.set_operator_snapshot(_operator_snapshot())

    assert view._authority_experiment_id is None
    assert view._quick_log is not None
    view._quick_log._input.setText("Глобальная запись")
    view._quick_log._on_submit()

    worker = _DeferredWorker.instances.pop(0)
    assert "experiment_id" not in worker.payload
    assert worker.payload["experiment_unbound"] is True
    assert worker.started is True


def test_dashboard_quick_log_poll_is_single_flight_and_coalesced(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    _settle_connection(view, experiment_id="exp-log")

    view._poll_log_entries()
    first = _DeferredWorker.instances[0]
    for _ in range(20):
        view._poll_log_entries()

    assert _DeferredWorker.instances == [first]
    assert view._log_poll_pending is True
    first.finish(_scope_result([]))
    app.processEvents()

    assert len(_DeferredWorker.instances) == 2
    assert _DeferredWorker.instances[-1] is not first
    assert view._log_poll_pending is False


def test_dashboard_phase_command_requires_exact_experiment_and_reconciles(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    _settle_connection(view, experiment_id="exp-exact")
    view.on_experiment_status(
        {
            "active_experiment": {"experiment_id": "exp-exact", "name": "E"},
            "current_phase": "vacuum",
            "phase_started_at": 1.0,
        }
    )

    view._on_phase_transition_requested("cooldown")

    assert len(_DeferredWorker.instances) == 1
    mutation = _DeferredWorker.instances.pop(0)
    context = view._phase_context
    assert context is not None
    assert mutation.payload == {
        "cmd": "experiment_advance_phase",
        "experiment_id": "exp-exact",
        "phase": "cooldown",
        "operator": "",
        "expected_experiment_id": "exp-exact",
    }
    mutation.finish(_phase_commit_result(context))

    assert len(_DeferredWorker.instances) == 1
    reconcile = _DeferredWorker.instances.pop(0)
    assert reconcile.payload == {"cmd": "experiment_phase_status"}
    reconcile.finish(
        {
            "ok": True,
            "experiment_id": "exp-exact",
            "current_phase": "cooldown",
            "phases": [],
        }
    )

    assert view._phase_context is None
    assert view._phase_widget._current_phase == "cooldown"
    assert view._phase_widget._operation_label.isHidden()


def test_dashboard_phase_command_without_exact_id_never_constructs_worker(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    _settle_connection(view, experiment_id="exp-authorized")
    view.on_experiment_status(
        {
            "active_experiment": {"name": "Legacy-shaped status"},
            "current_phase": "vacuum",
        }
    )

    view._on_phase_transition_requested("cooldown")

    assert _DeferredWorker.instances == []
    assert view._phase_widget._operation_label.text() == "ФАЗА НЕ ИЗМЕНЕНА"
    assert "идентификатора" in view._phase_widget._operation_label.toolTip()


def test_dashboard_phase_timeout_never_replays_mutation_and_uses_ordered_read(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    _settle_connection(view, experiment_id="exp-timeout")
    view.on_experiment_status(
        {
            "active_experiment": {"experiment_id": "exp-timeout"},
            "current_phase": "vacuum",
        }
    )
    view._on_phase_transition_requested("cooldown")
    mutation = _DeferredWorker.instances.pop(0)

    mutation.finish({"ok": False, "error": "Engine не отвечает (TimeoutError)", "_unknown": True})

    assert view._phase_widget._operation_label.text() == "ИСХОД НЕИЗВЕСТЕН"
    assert len(_DeferredWorker.instances) == 1
    reconcile = _DeferredWorker.instances.pop(0)
    assert reconcile.payload["cmd"] == "experiment_phase_status"
    reconcile.finish(
        {
            "ok": True,
            "experiment_id": "exp-timeout",
            "current_phase": "vacuum",
            "phases": [],
        }
    )

    assert view._phase_context is None
    assert view._phase_widget._operation_label.text() == "ФАЗА НЕ ИЗМЕНЕНА"
    assert all(worker.payload.get("cmd") != "experiment_advance_phase" for worker in _DeferredWorker.instances)


def test_dashboard_ignores_phase_reply_after_experiment_context_changes(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    _settle_connection(view, experiment_id="exp-old")
    view.on_experiment_status(
        {
            "active_experiment": {"experiment_id": "exp-old"},
            "current_phase": "vacuum",
        }
    )
    view._on_phase_transition_requested("cooldown")
    stale_worker = _DeferredWorker.instances.pop(0)
    stale_context = view._phase_context
    assert stale_context is not None

    view.on_experiment_status(
        {
            "active_experiment": {"experiment_id": "exp-new"},
            "current_phase": "preparation",
        }
    )
    stale_worker.finish(_phase_commit_result(stale_context))

    assert view._phase_widget.active_experiment_id == "exp-new"
    assert view._phase_widget._current_phase == "preparation"
    assert view._phase_context is None
    assert _DeferredWorker.instances == []


@pytest.mark.parametrize(
    ("identity_name", "stale_seconds", "identity_tail"),
    [
        ("REFUSED", 0, "\u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e"),
        ("LEGACY_ABSENT", 0, "\u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442"),
        ("AUTHORITATIVE", 60, None),
    ],
)
def test_dashboard_disconnect_keeps_interval_fault_across_identity_and_stale_axes(
    app,
    identity_name: str,
    stale_seconds: int,
    identity_tail: str | None,
) -> None:
    """One accepted cut cannot lose its worst interval status on disconnect."""
    from datetime import timedelta

    from cryodaq.drivers.base import ChannelStatus
    from cryodaq.gui import theme
    from cryodaq.gui.state.descriptor_store import IdentityStatus

    manager = ChannelManager()
    view = DashboardView(manager)
    now = datetime.now(UTC)
    final_identity = IdentityStatus[identity_name]
    samples = (
        (77.0, ChannelStatus.OK, IdentityStatus.AUTHORITATIVE, now),
        (500.0, ChannelStatus.OVERRANGE, IdentityStatus.AUTHORITATIVE, now),
        (78.0, ChannelStatus.OK, final_identity, now - timedelta(seconds=stale_seconds)),
    )
    for value, status, identity, timestamp in samples:
        view.on_reading(
            Reading(
                channel="\u04221",
                value=value,
                unit="K",
                timestamp=timestamp,
                status=status,
                instrument_id="lakeshore_218s",
            ),
            identity,
        )
    view._sensor_grid.refresh()
    assert view._sensor_grid._last_presentations["\u04221"][2] is ChannelStatus.OVERRANGE

    view._sensor_grid.refresh()
    assert view._sensor_grid._last_presentations["\u04221"][2] is ChannelStatus.OVERRANGE

    view.set_connected(False)
    cell = view._sensor_grid._cells["\u04221"]
    direct_text = cell._status_hint_widget.text()
    expected_fault = (
        "\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439 "
        "\u043f\u0440\u0438\u043d\u044f\u0442\u044b\u0439 "
        "\u0441\u0442\u0430\u0442\u0443\u0441: "
        "\u041f\u0435\u0440\u0435\u0433\u0440\u0443\u0437\u043a\u0430"
    )
    assert "\u041d\u0435\u0442 \u0441\u0432\u044f\u0437\u0438" in direct_text
    assert expected_fault in direct_text
    if identity_tail is not None:
        assert identity_tail in direct_text
    assert cell.accessibleDescription() == direct_text
    assert "dashed" in cell.styleSheet()
    assert f"border-left: 4px solid {theme.STATUS_FAULT}" in cell.styleSheet()

    manager._notify()
    rebuilt = view._sensor_grid._cells["\u04221"]
    assert rebuilt is not cell
    assert rebuilt._status_hint_widget.text() == direct_text
    assert rebuilt.accessibleDescription() == direct_text
    assert "dashed" in rebuilt.styleSheet()
    assert f"border-left: 4px solid {theme.STATUS_FAULT}" in rebuilt.styleSheet()


def test_dashboard_identity_banner_separates_historical_and_current_refusals(app) -> None:
    """Partial recovery must not label a fresh refusal as disconnected history."""
    from cryodaq.drivers.base import ChannelStatus
    from cryodaq.gui.state.descriptor_store import IdentityStatus

    manager = ChannelManager()
    view = DashboardView(manager)
    for channel in ("\u04221", "\u04222"):
        view.on_reading(
            Reading.now(
                channel=channel,
                value=4.2,
                unit="K",
                instrument_id="lakeshore_218s",
                status=ChannelStatus.OK,
            ),
            IdentityStatus.REFUSED,
        )
    view._sensor_grid.refresh()
    view.set_connected(False)
    view.set_connected(True)
    view.on_reading(
        Reading.now(
            channel="\u04222",
            value=4.1,
            unit="K",
            instrument_id="lakeshore_218s",
            status=ChannelStatus.OK,
        ),
        IdentityStatus.REFUSED,
    )
    view._sensor_grid.refresh()

    assert view._sensor_grid._accepted_after_transport_loss == {"\u04222"}
    historical = (
        "\u041d\u0435\u0442 \u0441\u0432\u044f\u0437\u0438 \u00b7 "
        "\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u044f\u044f "
        "\u0438\u0434\u0435\u043d\u0442\u0438\u0444\u0438\u043a\u0430\u0446\u0438\u044f: "
        "\u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u043a\u0430\u043d\u0430\u043b\u0430 "
        "\u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e (1)"
    )
    current = (
        "\u0414\u0430\u043d\u043d\u044b\u0435 \u043d\u0435 "
        "\u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u044b: "
        "\u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u043a\u0430\u043d\u0430\u043b\u0430 "
        "\u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e (1)"
    )
    expected = f"{historical}; {current}"
    banner = view._sensor_grid._identity_banner
    assert banner.text() == expected
    assert banner.accessibleName() == expected
    assert "dashed" in banner.styleSheet()


def test_dashboard_hiding_channel_prunes_transport_receipts(app) -> None:
    """Visibility changes bound retained presentations and recovery receipts."""
    from cryodaq.drivers.base import ChannelStatus
    from cryodaq.gui.state.descriptor_store import IdentityStatus

    manager = ChannelManager()
    view = DashboardView(manager)
    view.set_connected(False)
    view.set_connected(True)
    for channel in ("\u04221", "\u04222"):
        view.on_reading(
            Reading.now(
                channel=channel,
                value=4.2,
                unit="K",
                instrument_id="lakeshore_218s",
                status=ChannelStatus.OK,
            ),
            IdentityStatus.AUTHORITATIVE,
        )
    view._sensor_grid.refresh()
    assert {"\u04221", "\u04222"} <= set(view._sensor_grid._last_presentations)
    assert {"\u04221", "\u04222"} <= view._sensor_grid._accepted_after_transport_loss

    manager.set_visible("\u04222", False)
    manager._notify()

    assert "\u04221" in view._sensor_grid._cells
    assert "\u04221" in view._sensor_grid._last_presentations
    assert "\u04221" in view._sensor_grid._accepted_after_transport_loss
    assert "\u04222" not in view._sensor_grid._cells
    assert "\u04222" not in view._sensor_grid._last_presentations
    assert "\u04222" not in view._sensor_grid._accepted_after_transport_loss
