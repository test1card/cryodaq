"""Regression guards for conductivity persistence and reservation settlement."""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import cryodaq.gui.shell.overlays.conductivity_panel as panel_module
import cryodaq.storage.conductivity_run as run_storage
from cryodaq.gui.shell.overlays.conductivity_panel import ConductivityPanel
from cryodaq.storage.conductivity_run import ConductivityRunWriter, read_conductivity_run


class _Signal:
    def __init__(self) -> None:
        self._callbacks: list = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, result: dict) -> None:
        for callback in list(self._callbacks):
            callback(result)


class _ImmediatePersistenceWorker:
    def __init__(self, operation, *, cleanup_on_interruption=None) -> None:
        self._operation = operation
        self._cleanup_on_interruption = cleanup_on_interruption
        self._running = False
        self._interrupted = False
        self.completed = _Signal()

    def start(self, *_args) -> None:
        self._running = True
        try:
            value = self._operation()
        except BaseException as exc:
            result = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        else:
            result = {"ok": True, "value": value}
        self._running = False
        if not self._interrupted:
            self.completed.emit(result)

    def requestInterruption(self) -> None:
        self._interrupted = True
        if self._cleanup_on_interruption is not None:
            self._cleanup_on_interruption()

    def isRunning(self) -> bool:
        return self._running


class _DeferredCommandWorker:
    instances: list[_DeferredCommandWorker] = []

    def __init__(self, cmd: dict, *, parent=None) -> None:
        del parent
        self.cmd = dict(cmd)
        self.finished = _Signal()
        self.running = False
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.running = True

    def isRunning(self) -> bool:
        return self.running

    def finish(self, result: dict) -> None:
        self.running = False
        self.finished.emit(result)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolated_workers(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CRYODAQ_STATE_ROOT", str(tmp_path / "state"))
    _DeferredCommandWorker.instances.clear()
    monkeypatch.setattr(panel_module, "_ConductivityPersistenceWorker", _ImmediatePersistenceWorker)
    monkeypatch.setattr(panel_module, "ZmqCommandWorker", _DeferredCommandWorker)


def _matching_attachment_reply(worker: _DeferredCommandWorker, experiment_id: str = "experiment-a") -> dict:
    command = worker.cmd
    return {
        "ok": True,
        "attached": True,
        "run_record": {
            "source_run_id": command["source_run_id"],
            "status": command["status"],
            "parameters": command["parameters"],
            "result_summary": command["result_summary"],
            "artifact_paths": command["artifact_paths"],
            "experiment_context": {"experiment_id": experiment_id},
        },
    }


def _seed_run_identity(panel: ConductivityPanel, tmp_path, *, create_writer: bool) -> ConductivityRunWriter | None:
    started_at = datetime(2026, 8, 29, 12, tzinfo=UTC)
    path = tmp_path / "conductivity-race.csv"
    parameters = {"power_values_w": [0.01]}
    panel._auto_state = "stabilizing"
    panel._auto_run_path = path
    panel._auto_run_id = "conductivity-race"
    panel._auto_run_started_at = started_at
    panel._auto_run_parameters = parameters
    panel._auto_power_list = [0.01]
    if not create_writer:
        return None
    writer = ConductivityRunWriter(
        path,
        run_id=panel._auto_run_id,
        started_at=started_at,
        parameters=parameters,
    )
    writer.append_binding("experiment-a")
    panel._auto_run_writer = writer
    panel._auto_experiment_id = "experiment-a"
    panel._auto_experiment_binding_known = True
    panel._auto_binding_resolution = "durable"
    return writer


def test_terminal_fsync_error_reconciles_disk_and_retries_metadata_attachment(
    app,
    monkeypatch,
    tmp_path,
) -> None:
    panel = ConductivityPanel()
    panel.set_connected(True)
    writer = _seed_run_identity(panel, tmp_path, create_writer=True)
    assert writer is not None
    panel._auto_verified_off_connection_generation = panel._auto_connection_generation
    real_fsync = run_storage.os.fsync
    terminal_syncs = 0

    def _fsync_then_raise(fd: int) -> None:
        nonlocal terminal_syncs
        terminal_syncs += 1
        real_fsync(fd)
        if terminal_syncs == 1:
            raise OSError("deterministic post-terminal-fsync failure")

    monkeypatch.setattr(run_storage.os, "fsync", _fsync_then_raise)

    panel._begin_terminalize_auto_run("COMPLETED")

    assert terminal_syncs == 1, "mutation anchor did not reach the terminal fsync"
    snapshot = read_conductivity_run(panel._auto_run_path)
    assert snapshot.status == "COMPLETED"
    assert snapshot.terminal is not None
    assert panel.get_auto_state() == "stabilizing"
    assert panel._auto_outcome_unknown is False
    assert len(_DeferredCommandWorker.instances) == 1
    attachment = _DeferredCommandWorker.instances[0]
    assert attachment.cmd["cmd"] == "experiment_attach_run_record"
    assert attachment.cmd["status"] == "COMPLETED"
    assert attachment.cmd["result_summary"]["point_count"] == 0

    attachment.finish(_matching_attachment_reply(attachment))

    assert panel.get_auto_state() == "done"
    assert panel._auto_terminal_attachment_command is None


def test_settled_malformed_reservation_enters_failure_and_stop_reconciles_terminal_record(
    app,
    tmp_path,
) -> None:
    panel = ConductivityPanel()
    panel.set_connected(True)
    _seed_run_identity(panel, tmp_path, create_writer=False)
    command = panel._attachment_command(
        status="RUNNING",
        terminal=None,
        finished_at=None,
        reservation_state="reserved",
    )
    assert command is not None
    panel._auto_binding_resolution = "reservation_pending"
    panel._auto_command_sequence = 1
    panel._auto_pending_token = 1

    panel._on_auto_cmd_result(
        1,
        command,
        {"ok": True, "attached": True, "run_record": {"source_run_id": "wrong-run"}},
        panel._auto_connection_generation,
        panel._auto_operation_generation,
    )

    assert panel._auto_binding_resolution == "reservation_failed"
    assert panel._auto_pending_token is None
    assert panel._auto_outcome_unknown is True
    assert panel._auto_stop_btn.isEnabled() is True

    panel._on_auto_stop()
    stop_worker = _DeferredCommandWorker.instances[-1]
    assert stop_worker.cmd == {"cmd": "keithley_stop", "channel": "smua"}
    stop_worker.finish({"ok": True})

    reconciliation = _DeferredCommandWorker.instances[-1]
    assert reconciliation is not stop_worker
    assert reconciliation.cmd["cmd"] == "experiment_attach_run_record"
    assert reconciliation.cmd["status"] == "RUNNING"
    assert panel._auto_binding_resolution == "reservation_reconciliation_pending"
    assert panel._auto_stop_btn.isEnabled() is False
    reconciliation.finish(_matching_attachment_reply(reconciliation))

    terminal_attachment = _DeferredCommandWorker.instances[-1]
    assert terminal_attachment not in {stop_worker, reconciliation}
    assert terminal_attachment.cmd["cmd"] == "experiment_attach_run_record"
    assert terminal_attachment.cmd["status"] == "ABORTED"
    terminal_attachment.finish(_matching_attachment_reply(terminal_attachment))

    snapshot = read_conductivity_run(panel._auto_run_path)
    assert snapshot.status == "ABORTED"
    assert snapshot.binding_recorded is True
    assert snapshot.bound_experiment_id == "experiment-a"
    assert panel.get_auto_state() == "idle"
    assert panel._auto_pending_stop_intent is None
    assert panel._auto_stop_btn.isEnabled() is False
