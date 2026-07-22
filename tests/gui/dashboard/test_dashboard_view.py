"""Smoke tests for DashboardView skeleton (Phase UI-1 v2 Block B.1)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QScrollArea

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.gui.dashboard import DashboardView
from cryodaq.gui.dashboard.dashboard_view import _PRESENTATION_INTERVAL_MS


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


def _settle_connection(view: DashboardView) -> None:
    view.set_connected(True)
    assert len(_DeferredWorker.instances) == 1
    _DeferredWorker.instances.pop(0).finish(_scope_result([]))


def _commit_result(context: dict, *, entry_id: int = 1) -> dict:
    entry = {
        "id": entry_id,
        "timestamp": "2026-07-19T08:00:00+00:00",
        "message": context["message"],
    }
    return {
        "ok": True,
        "committed": True,
        "entry": entry,
        "commit_receipt": {
            "schema": "operator_log_commit_v1",
            "request_id": context["request_id"],
            "entry_id": entry_id,
            "experiment_id": None,
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

    view._sensor_grid.rename_requested.emit("Т1", "Новое")
    view._sensor_grid.hide_requested.emit("Т1")
    app.processEvents()

    assert mgr.get_name("Т1") == "Новое"
    assert mgr.is_visible("Т1") is False
    assert saved == [True, True]


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
    _settle_connection(view)
    assert view._quick_log is not None
    view._quick_log._input.setText("Проверить persistence-first")

    view._quick_log._on_submit()

    assert len(_DeferredWorker.instances) == 1
    worker = _DeferredWorker.instances.pop(0)
    context = view._log_submit_context
    assert context is not None
    assert worker.payload == context["payload"]
    assert worker.payload["cmd"] == "log_entry"
    assert worker.payload["experiment_unbound"] is True
    assert "experiment_id" not in worker.payload
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
    _settle_connection(view)
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
    _settle_connection(view)
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


def test_dashboard_quick_log_accepts_exact_late_receipt_after_disconnect(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    _settle_connection(view)
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


def test_dashboard_quick_log_poll_is_single_flight_and_coalesced(app, monkeypatch):
    _install_deferred_worker(monkeypatch)
    view = DashboardView(ChannelManager())
    _settle_connection(view)

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
    _settle_connection(view)
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
    _settle_connection(view)
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
    _settle_connection(view)
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
    _settle_connection(view)
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
