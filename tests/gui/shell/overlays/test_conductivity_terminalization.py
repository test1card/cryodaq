"""Terminalization regressions kept outside the blob-bound conductivity guard."""

from __future__ import annotations

from cryodaq.gui.shell.overlays import conductivity_panel as panel_module
from cryodaq.gui.shell.overlays.conductivity_panel import ConductivityPanel
from tests.gui.shell.overlays import test_conductivity_panel as guard_support

app = guard_support.app
_isolated_state_root = guard_support._isolated_state_root


def test_stop_before_failed_running_attachment_resumes_deferred_terminalization(app, monkeypatch) -> None:
    guard_support._DeferredWorker.defer_running_attachment = True
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", guard_support._DeferredWorker)
    panel = ConductivityPanel()
    guard_support._stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._on_auto_start()
    attachment_worker = guard_support._DeferredWorker.instances[-1]
    assert attachment_worker.cmd["cmd"] == "experiment_attach_run_record"
    assert attachment_worker.cmd["status"] == "RUNNING"

    panel._on_auto_stop()
    stop_worker = guard_support._DeferredWorker.instances[-1]
    assert stop_worker is not attachment_worker
    stop_worker.finish({"ok": True})
    assert panel._auto_deferred_terminal_status == "ABORTED"

    attachment_worker.finish({"ok": False, "error": "attachment failed"})

    assert panel._auto_run_path is not None
    snapshot = guard_support.read_conductivity_run(panel._auto_run_path)
    assert snapshot.status == "ABORTED"
    assert snapshot.binding_recorded is True
    assert snapshot.bound_experiment_id is None
    assert panel.get_auto_state() == "idle"
    assert panel._auto_pending_stop_intent is None
    assert panel._auto_outcome_unknown is False
    assert all(worker.cmd.get("cmd") != "keithley_set_target" for worker in guard_support._DeferredWorker.all_instances)


def test_failed_running_attachment_waits_for_outstanding_stop_before_confirming_off(app, monkeypatch) -> None:
    guard_support._DeferredWorker.defer_running_attachment = True
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", guard_support._DeferredWorker)
    panel = ConductivityPanel()
    guard_support._stub_channels(panel, ["Т1", "Т2"])
    panel._checkboxes["Т1"].setChecked(True)
    panel._checkboxes["Т2"].setChecked(True)
    panel.set_connected(True)

    panel._on_auto_start()
    attachment_worker = guard_support._DeferredWorker.instances[-1]
    assert attachment_worker.cmd["cmd"] == "experiment_attach_run_record"
    assert attachment_worker.cmd["status"] == "RUNNING"

    panel._on_auto_stop()
    stop_worker = guard_support._DeferredWorker.instances[-1]
    assert stop_worker is not attachment_worker
    assert stop_worker.cmd == {"cmd": "keithley_stop", "channel": "smua"}

    attachment_worker.finish({"ok": True, "attached": False, "run_record": None})

    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_pending_stop_intent == "operator"
    assert stop_worker.isRunning()
    assert stop_worker in panel._auto_workers
    assert "ожидается подтверждение отключения источника" in panel._auto_status_label.text()
    assert "отключение подтверждено" not in panel._auto_status_label.text()

    stop_worker.finish({"ok": True})

    assert panel.get_auto_state() == "idle"
    assert panel._auto_pending_stop_intent is None
    assert panel._auto_outcome_unknown is False
    assert "отключение подтверждено" in panel._auto_status_label.text()
