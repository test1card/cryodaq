"""Focused contract tests for the authoritative phase-aware alarm overlay."""

from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from cryodaq.core.alarm_ack_codec import (
    ALARM_ACK_COMMIT_SCHEMA,
    alarm_ack_request_fingerprint,
    deterministic_alarm_ack_request_id,
)
from cryodaq.core.annunciation import AnnunciationRegistry
from cryodaq.core.zmq_bridge import ZMQCommandServer
from cryodaq.gui import theme
from cryodaq.gui.shell.operator_components._visuals import plain_text_tooltip
from cryodaq.gui.shell.overlays.alarm_panel import (
    AlarmPanel,
    SeverityChip,
    _elapsed_text,
    _make_ack_button,
)
from cryodaq.gui.zmq_client import CLIENT_PROTOCOL_VERSION

_ENGINE_A = "a" * 32
_ENGINE_B = "b" * 32


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


class _FakeSignal:
    def __init__(self) -> None:
        self._slot = None

    def connect(self, slot) -> None:
        self._slot = slot

    def emit(self, *args) -> None:
        if self._slot is not None:
            self._slot(*args)


class _StubWorker:
    dispatched: list[dict] = []
    next_result: dict | None = None

    def __init__(self, cmd, *, parent=None, release_on_settle: bool = False) -> None:
        self._cmd = dict(cmd)
        self.dispatched.append(self._cmd)
        self.finished = _FakeSignal()

    def start(self) -> None:
        if self.next_result is not None:
            self.finished.emit(self.next_result)

    def isRunning(self) -> bool:
        return False


@pytest.fixture(autouse=True)
def _reset_stub(monkeypatch):
    import cryodaq.gui.shell.overlays.alarm_panel as module

    _StubWorker.dispatched = []
    _StubWorker.next_result = None
    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)


def _handler_payload(
    *,
    acknowledged: bool = False,
    engine_instance_id: str = _ENGINE_A,
    snapshot_revision: int = 1,
    active: dict | None = None,
) -> dict:
    if active is None:
        active = {
            "cold": {
                "level": "CRITICAL",
                "activation_id": "activation-a",
                "message": "plate hot",
                "channels": ["T11"],
                "triggered_at": time.time() - 10,
                "acknowledged": acknowledged,
                "acknowledged_at": time.time() if acknowledged else 0.0,
                "acknowledged_by": "operator-a" if acknowledged else "",
                "evaluator_error": False,
            }
        }
    return {
        "ok": True,
        "engine_instance_id": engine_instance_id,
        "snapshot_revision": snapshot_revision,
        "history": [],
        "active": active,
    }


def _wire_from_handler(handler_payload: dict) -> dict:
    assert "proto" not in handler_payload
    return json.loads(ZMQCommandServer(handler=None)._encode_reply(handler_payload))


def _wire_payload(**kwargs: object) -> dict:
    return _wire_from_handler(_handler_payload(**kwargs))


def _payload(*, acknowledged: bool = False) -> dict:
    return _wire_payload(acknowledged=acknowledged)


def _ack_command() -> dict[str, str]:
    semantic = {
        "cmd": "alarm_v2_ack",
        "alarm_name": "cold",
        "engine_instance_id": _ENGINE_A,
        "activation_id": "activation-a",
        "operator": "operator-a",
        "reason": "observed locally",
    }
    return {
        **semantic,
        "request_id": deterministic_alarm_ack_request_id(
            alarm_name=semantic["alarm_name"],
            engine_instance_id=semantic["engine_instance_id"],
            activation_id=semantic["activation_id"],
            operator=semantic["operator"],
            reason=semantic["reason"],
        ),
    }


def _ack_wire_result(command: dict[str, str], state: str) -> dict[str, object]:
    fingerprint = alarm_ack_request_fingerprint(command)
    common: dict[str, object] = {
        "ok": state == "published",
        "committed": state != "aborted",
        "retry_safe": False,
        "publication_state": state,
        "event_emitted": state == "published",
        "alarm_name": command["alarm_name"],
        "activation_id": command["activation_id"],
        "engine_instance_id": command["engine_instance_id"],
        "source_activation_id": "7",
        "request_id": command["request_id"],
    }
    if state in {"published", "pending"}:
        common["commit_receipt"] = {
            "schema": ALARM_ACK_COMMIT_SCHEMA,
            "request_id": command["request_id"],
            "request_fingerprint": fingerprint,
            "alarm_name": command["alarm_name"],
            "activation_id": command["activation_id"],
            "engine_instance_id": command["engine_instance_id"],
            "source_activation_id": "7",
            "acknowledged_at": 123.5,
            "committed": True,
        }
        if state == "pending":
            common.update(
                error_code="alarm_ack_publication_pending",
                error="alarm acknowledgement is committed; publication settlement is pending",
            )
    elif state == "aborted":
        common.update(
            error_code="alarm_ack_aborted",
            error="alarm acknowledgement was terminally aborted before durable commit",
            request_fingerprint=fingerprint,
            terminal_code="activation_changed_before_ack_commit",
            terminal_engine_instance_id=command["engine_instance_id"],
        )
    else:  # pragma: no cover - test-helper misuse
        raise ValueError(f"unsupported ACK settlement: {state}")
    return _wire_from_handler(common)


def _dispose_panel(panel: AlarmPanel, app: QApplication) -> None:
    panel.set_connected(False)
    if panel._v2_poll_timer is not None:
        panel._v2_poll_timer.stop()
    if panel._cooldown_poll_timer is not None:
        panel._cooldown_poll_timer.stop()
    panel.close()
    panel.deleteLater()
    app.processEvents()


def test_panel_is_v2_only_and_unavailable_by_default(app):
    panel = AlarmPanel()
    assert panel.objectName() == "alarmPanel"
    assert panel._v2_alarms == {}
    assert panel._v2_table.columnCount() == 6
    assert not hasattr(panel, "_table")
    assert not hasattr(panel, "on_reading")
    assert not hasattr(panel, "get_active_v1_count")
    assert panel._body_stack.currentWidget() is panel._body_unavailable_page
    labels = panel._body_unavailable_page.findChildren(QLabel)
    assert any("недоступны" in label.text().casefold() for label in labels)
    assert not any("Нет активных тревог" in label.text() for label in labels)


@pytest.mark.parametrize("invalid", [0, 1, None, "true", object()])
def test_constructor_live_authority_requires_exact_bool(app, invalid: object) -> None:
    with pytest.raises(TypeError, match="live_authority must be an exact bool"):
        AlarmPanel(live_authority=invalid)


def test_replay_capability_constructs_no_live_timers_and_cannot_be_promoted(app):
    panel = AlarmPanel(live_authority=False)
    try:
        assert panel._live_capable is False
        assert panel._live_authority is False
        assert panel._v2_poll_timer is None
        assert panel._cooldown_poll_timer is None
        assert panel.findChildren(QTimer) == []

        panel.set_connected(True)
        with pytest.raises(RuntimeError, match="cannot be promoted"):
            panel.set_live_authority(True)

        assert panel._live_authority is False
        assert panel._v2_poll_timer is None
        assert panel._cooldown_poll_timer is None
        assert panel._body_stack.currentWidget() is panel._body_unavailable_page
    finally:
        _dispose_panel(panel, app)


def test_severity_presentation_uses_design_tokens_and_non_color_cues(app):
    critical = SeverityChip("CRITICAL")
    caution = SeverityChip("WARNING")
    acknowledged = SeverityChip("CRITICAL", acknowledged=True)
    assert critical.text() == "КРИТ"
    assert caution.text() == "ВНИМ"
    assert "✓" in acknowledged.text()
    assert theme.STATUS_FAULT in critical.styleSheet()
    assert theme.STATUS_CAUTION in caution.styleSheet()
    assert theme.SURFACE_MUTED in acknowledged.styleSheet()


def test_ack_button_uses_status_and_disabled_tokens(app):
    button = _make_ack_button("CRITICAL")
    assert button.text() == "ПОДТВЕРДИТЬ"
    assert theme.STATUS_FAULT in button.styleSheet()
    assert theme.SURFACE_MUTED in button.styleSheet()


def test_update_renders_complete_v2_evidence_and_count(app):
    panel = AlarmPanel()
    summaries: list[tuple[int, str]] = []
    panel.v2_alarm_summary_changed.connect(lambda count, level: summaries.append((count, level)))
    panel.update_v2_status(_payload())
    assert panel.get_active_v2_count() == 1
    assert summaries == [(1, "CRITICAL")]
    assert panel._body_stack.currentIndex() == 1
    assert panel._v2_table.rowCount() == 1
    assert isinstance(panel._v2_table.cellWidget(0, 0), SeverityChip)
    assert panel._v2_table.item(0, 1).text() == "cold"
    assert panel._v2_table.item(0, 2).text() == "plate hot"
    assert panel._v2_table.item(0, 3).text() == "T11"


def test_update_marks_alarm_held_by_evaluator_failure(app):
    panel = AlarmPanel()
    try:
        payload = _payload()
        payload["active"]["cold"]["evaluator_error"] = True
        panel.update_v2_status(payload)

        message = panel._v2_table.item(0, 2).text()
        assert "ОШИБКА ОЦЕНКИ" in message
        assert "удерживается" in message
        assert "plate hot" in message
        assert theme.STATUS_FAULT in panel._v2_table.item(0, 2).foreground().color().name()
    finally:
        _dispose_panel(panel, app)


def test_poll_accepts_only_the_real_zmq_encoded_status_envelope(app):
    panel = AlarmPanel()
    availability: list[bool] = []
    panel.v2_alarm_availability_changed.connect(availability.append)
    try:
        panel.set_connected(True)
        handler_payload = _handler_payload()
        assert "proto" not in handler_payload
        wire_payload = _wire_from_handler(handler_payload)
        assert wire_payload["proto"] == CLIENT_PROTOCOL_VERSION

        panel._v2_poll_in_flight = True
        panel._on_poll_v2_result(wire_payload, panel._connection_generation)

        assert panel._v2_poll_in_flight is False
        assert panel._v2_snapshot_authoritative is True
        assert set(panel._v2_alarms) == {"cold"}
        assert availability[-1] is True
    finally:
        _dispose_panel(panel, app)


def test_raw_handler_status_without_transport_envelope_revokes_authority(app):
    panel = AlarmPanel()
    try:
        panel.update_v2_status(_payload())
        panel.set_connected(True)
        raw_handler_payload = _handler_payload(snapshot_revision=2, active={})
        assert "proto" not in raw_handler_payload

        panel._v2_poll_in_flight = True
        panel._on_poll_v2_result(raw_handler_payload, panel._connection_generation)

        assert set(panel._v2_alarms) == {"cold"}
        assert panel._v2_engine_instance_id == _ENGINE_A
        assert panel._v2_snapshot_revision == 1
        assert panel._v2_snapshot_authoritative is False
        assert not panel._v2_table.cellWidget(0, 5).isEnabled()
    finally:
        _dispose_panel(panel, app)


def test_acknowledged_alarm_stays_visible_but_leaves_attention_count(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload(acknowledged=True))
    assert panel.get_active_v2_count() == 0
    assert panel._v2_table.rowCount() == 1
    assert panel._v2_table.cellWidget(0, 5) is None
    assert panel._v2_table.item(0, 5).text() == "Подтв. (operator-a)"
    chip = panel._v2_table.cellWidget(0, 0)
    assert isinstance(chip, SeverityChip)
    assert "✓" in chip.text()


@pytest.mark.parametrize(
    ("acknowledged", "acknowledged_at", "acknowledged_by"),
    [
        pytest.param(True, 0.0, "operator-a", id="ack-with-zero-time"),
        pytest.param(True, 1.0, "", id="ack-with-empty-operator"),
        pytest.param(True, 1.0, "   ", id="ack-with-whitespace-operator"),
        pytest.param(True, 1.0, "operator" + chr(10) + "forged", id="ack-with-control-operator"),
        pytest.param(False, 1.0, "", id="unack-with-positive-time"),
        pytest.param(False, 0.0, "operator-a", id="unack-with-operator"),
    ],
)
def test_acknowledgement_cross_fields_fail_closed_as_one_authority_cut(
    app,
    acknowledged: bool,
    acknowledged_at: float,
    acknowledged_by: str,
):
    panel = AlarmPanel()
    try:
        panel.update_v2_status(_payload())
        panel.set_connected(True)
        candidate = _handler_payload(snapshot_revision=2)
        row = candidate["active"]["cold"]
        row["acknowledged"] = acknowledged
        row["acknowledged_at"] = acknowledged_at
        row["acknowledged_by"] = acknowledged_by

        panel.update_v2_status(_wire_from_handler(candidate))

        assert panel._v2_snapshot_revision == 1
        assert panel._v2_snapshot_authoritative is False
        assert panel._v2_alarms["cold"]["acknowledged"] is False
        assert not panel._v2_table.cellWidget(0, 5).isEnabled()
    finally:
        _dispose_panel(panel, app)


@pytest.mark.parametrize(
    ("acknowledged", "acknowledged_at", "acknowledged_by"),
    [
        pytest.param(False, 0.0, "", id="unacknowledged"),
        pytest.param(True, 1.0, "operator-a", id="acknowledged"),
    ],
)
def test_acknowledgement_cross_fields_accept_only_complete_consistent_cuts(
    app,
    acknowledged: bool,
    acknowledged_at: float,
    acknowledged_by: str,
):
    panel = AlarmPanel()
    try:
        candidate = _handler_payload(acknowledged=acknowledged)
        row = candidate["active"]["cold"]
        row["acknowledged_at"] = acknowledged_at
        row["acknowledged_by"] = acknowledged_by

        panel.update_v2_status(_wire_from_handler(candidate))

        assert panel._v2_snapshot_authoritative is True
        assert panel._v2_alarms["cold"]["acknowledged"] is acknowledged
        assert panel._v2_alarms["cold"]["acknowledged_at"] == acknowledged_at
        assert panel._v2_alarms["cold"]["acknowledged_by"] == acknowledged_by
    finally:
        _dispose_panel(panel, app)


def test_exact_activation_ack_dispatches_captured_identity(app, monkeypatch):
    import cryodaq.gui.shell.overlays.alarm_panel as module

    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    _StubWorker.dispatched = []
    button = panel._v2_table.cellWidget(0, 5)
    assert isinstance(button, QPushButton)
    assert button.isEnabled()
    answers = iter([("operator-a", True), ("observed locally", True)])
    monkeypatch.setattr(module.QInputDialog, "getText", lambda *_args, **_kwargs: next(answers))
    button.click()
    request_id = deterministic_alarm_ack_request_id(
        alarm_name="cold",
        engine_instance_id=_ENGINE_A,
        activation_id="activation-a",
        operator="operator-a",
        reason="observed locally",
    )
    assert _StubWorker.dispatched == [
        {
            "cmd": "alarm_v2_ack",
            "alarm_name": "cold",
            "engine_instance_id": _ENGINE_A,
            "activation_id": "activation-a",
            "operator": "operator-a",
            "reason": "observed locally",
            "request_id": request_id,
        }
    ]
    panel._v2_poll_timer.stop()


def test_pending_ack_remains_reachable_after_acknowledged_snapshot_and_retries_exact_command(app, monkeypatch):
    panel = AlarmPanel()
    try:
        panel.update_v2_status(_payload())
        panel.set_connected(True)
        command = _ack_command()
        pending_key = (_ENGINE_A, "activation-a")
        panel._pending_ack_commands[pending_key] = command
        panel._pending_ack_states[pending_key] = "submitting"
        panel._pending_ack_in_flight.add(pending_key)

        panel._on_ack_v2_result(_ack_wire_result(command, "pending"), "cold", command)
        panel.update_v2_status(_wire_payload(acknowledged=True, snapshot_revision=2))

        assert panel._pending_ack_commands[pending_key] is command
        assert panel._pending_ack_states[pending_key] == "pending"
        assert pending_key not in panel._pending_ack_in_flight
        assert not panel._ack_settlement_button.isHidden()
        assert panel._ack_settlement_button.isEnabled()
        row_button = panel._v2_table.cellWidget(0, 5)
        assert isinstance(row_button, QPushButton)
        assert row_button.property("retainedPendingAck") is True

        retried: list[dict[str, str]] = []
        monkeypatch.setattr(panel, "_dispatch_pending_ack", retried.append)
        panel._retry_next_pending_ack()
        assert retried == [command]
        assert retried[0] is command
    finally:
        _dispose_panel(panel, app)


def test_pending_ack_retry_is_single_flight_and_terminal_publication_frees_capacity(app):
    panel = AlarmPanel()
    try:
        panel.update_v2_status(_payload())
        panel.set_connected(True)
        command = _ack_command()
        pending_key = (_ENGINE_A, "activation-a")
        panel._pending_ack_commands[pending_key] = command
        panel._pending_ack_states[pending_key] = "pending"
        _StubWorker.dispatched = []
        _StubWorker.next_result = None

        panel._retry_pending_ack(pending_key)
        panel._retry_pending_ack(pending_key)

        assert _StubWorker.dispatched == [command]
        assert pending_key in panel._pending_ack_in_flight
        assert not panel._ack_settlement_button.isEnabled()

        panel._on_ack_v2_result(_ack_wire_result(command, "published"), "cold", command)

        assert panel._pending_ack_commands == {}
        assert panel._pending_ack_states == {}
        assert panel._pending_ack_in_flight == set()
        assert panel._ack_settlement_button.isHidden()
    finally:
        _dispose_panel(panel, app)


@pytest.mark.parametrize("terminal_state", ["published", "aborted"])
def test_malformed_ack_result_cannot_release_retained_command_but_valid_terminal_result_can(
    app,
    terminal_state: str,
):
    panel = AlarmPanel()
    try:
        panel.update_v2_status(_payload())
        panel.set_connected(True)
        command = _ack_command()
        pending_key = (_ENGINE_A, "activation-a")
        panel._pending_ack_commands[pending_key] = command
        panel._pending_ack_states[pending_key] = "pending"

        panel._on_ack_v2_result({"ok": True}, "cold", command)

        assert panel._pending_ack_commands[pending_key] is command
        assert panel._pending_ack_states[pending_key] == "outcome_unknown"
        assert not panel._ack_settlement_button.isHidden()

        panel._on_ack_v2_result(_ack_wire_result(command, terminal_state), "cold", command)

        assert pending_key not in panel._pending_ack_commands
        assert pending_key not in panel._pending_ack_states
        assert panel._ack_settlement_button.isHidden()
    finally:
        _dispose_panel(panel, app)


def test_pending_ack_stays_header_reachable_after_alarm_disappears_and_engine_replaces(app):
    panel = AlarmPanel()
    try:
        panel.update_v2_status(_payload())
        panel.set_connected(True)
        command = _ack_command()
        pending_key = (_ENGINE_A, "activation-a")
        panel._pending_ack_commands[pending_key] = command
        panel._pending_ack_states[pending_key] = "pending"
        panel._refresh_v2_table()

        panel.update_v2_status(_wire_payload(snapshot_revision=2, active={}))
        panel.update_v2_status(_wire_payload(engine_instance_id=_ENGINE_B, snapshot_revision=1, active={}))

        assert panel._pending_ack_commands[pending_key] is command
        assert not panel._ack_settlement_button.isHidden()
        assert panel._ack_settlement_button.isEnabled()
        assert "(1)" in panel._ack_settlement_button.text()
    finally:
        _dispose_panel(panel, app)


def test_pending_ack_affordance_is_fail_closed_when_disconnected_or_read_only(app):
    panel = AlarmPanel()
    try:
        command = _ack_command()
        pending_key = (_ENGINE_A, "activation-a")
        panel._pending_ack_commands[pending_key] = command
        panel._pending_ack_states[pending_key] = "pending"
        panel._refresh_pending_ack_affordance()

        assert not panel._ack_settlement_button.isHidden()
        assert not panel._ack_settlement_button.isEnabled()

        panel.set_connected(True)
        assert panel._ack_settlement_button.isEnabled()
        panel.set_read_only(True)
        assert not panel._ack_settlement_button.isEnabled()
        panel.set_read_only(False)
        assert panel._ack_settlement_button.isEnabled()
        panel.set_connected(False)
        assert not panel._ack_settlement_button.isEnabled()
    finally:
        _dispose_panel(panel, app)


def test_missing_exact_identity_keeps_evidence_but_disables_ack(app):
    panel = AlarmPanel()
    panel.update_v2_status({"ok": True, "active": {"cold": {"level": "CRITICAL"}}})
    panel.set_connected(True)
    assert panel._v2_table.rowCount() == 0
    assert "недоступны" in panel._summary_label.text().lower()
    panel._v2_poll_timer.stop()


def test_delayed_button_keeps_old_activation_identity(app, monkeypatch):
    import cryodaq.gui.shell.overlays.alarm_panel as module

    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    old_button = panel._v2_table.cellWidget(0, 5)
    newer = _payload()
    newer["snapshot_revision"] = 2
    newer["active"]["cold"]["activation_id"] = "activation-b"
    panel.update_v2_status(newer)
    _StubWorker.dispatched = []
    answers = iter([("operator-a", True), ("observed locally", True)])
    monkeypatch.setattr(module.QInputDialog, "getText", lambda *_args, **_kwargs: next(answers))
    old_button.click()
    assert _StubWorker.dispatched[0]["activation_id"] == "activation-a"
    panel._v2_poll_timer.stop()


def test_out_of_order_same_engine_snapshot_is_ignored(app):
    panel = AlarmPanel()
    try:
        current = _wire_payload(snapshot_revision=2)
        panel.update_v2_status(current)
        panel.set_connected(True)
        stale = json.loads(json.dumps(current))
        stale["snapshot_revision"] = 1
        stale["active"] = {
            "old": {
                **stale["active"]["cold"],
                "activation_id": "activation-old",
            }
        }

        panel.update_v2_status(stale)

        assert set(panel._v2_alarms) == {"cold"}
        assert panel._v2_snapshot_revision == 2
        assert panel._v2_snapshot_authoritative is True
        assert panel._v2_table.cellWidget(0, 5).isEnabled()
    finally:
        _dispose_panel(panel, app)


def test_malformed_stale_snapshot_retains_evidence_but_revokes_authority(app):
    panel = AlarmPanel()
    try:
        panel.update_v2_status(_wire_payload(snapshot_revision=2))
        panel.set_connected(True)
        malformed = _wire_payload(snapshot_revision=1)
        malformed["active"] = {"old": {"level": "CRITICAL", "activation_id": "old"}}

        panel.update_v2_status(malformed)

        assert set(panel._v2_alarms) == {"cold"}
        assert panel._v2_snapshot_revision == 2
        assert panel._v2_snapshot_authoritative is False
        assert not panel._v2_table.cellWidget(0, 5).isEnabled()
    finally:
        _dispose_panel(panel, app)


def test_replacement_engine_must_reach_revision_one_before_it_can_clear_evidence(app):
    panel = AlarmPanel()
    try:
        panel.update_v2_status(_wire_payload(engine_instance_id=_ENGINE_A, snapshot_revision=1))
        panel.set_connected(True)

        panel.update_v2_status(
            _wire_payload(
                engine_instance_id=_ENGINE_B,
                snapshot_revision=0,
                active={},
            )
        )

        assert set(panel._v2_alarms) == {"cold"}
        assert panel._v2_engine_instance_id == _ENGINE_A
        assert panel._v2_snapshot_revision == 1
        assert panel._v2_snapshot_authoritative is False
        assert not panel._v2_table.cellWidget(0, 5).isEnabled()

        panel.update_v2_status(
            _wire_payload(
                engine_instance_id=_ENGINE_B,
                snapshot_revision=1,
                active={},
            )
        )

        assert panel._v2_alarms == {}
        assert panel._v2_engine_instance_id == _ENGINE_B
        assert panel._v2_snapshot_revision == 1
        assert panel._v2_snapshot_authoritative is True
        assert panel._body_stack.currentWidget() is panel._body_empty_page
    finally:
        _dispose_panel(panel, app)


@pytest.mark.parametrize("active", [None, {}], ids=["nonempty", "empty"])
def test_fresh_panel_rejects_revision_zero_as_non_authoritative(app, active: dict | None):
    panel = AlarmPanel()
    try:
        panel.update_v2_status(_wire_payload(snapshot_revision=0, active=active))
        panel.set_connected(True)

        assert panel._v2_snapshot_authoritative is False
        assert panel._v2_engine_instance_id is None
        assert panel._v2_snapshot_revision == -1
        assert panel._v2_alarms == {}
        assert panel._v2_ack_buttons == []
        assert not panel._summary_label.isHidden()
        assert "недоступны" in panel._summary_label.text().lower()
    finally:
        _dispose_panel(panel, app)


def test_real_fresh_empty_registry_replacement_clears_only_after_complete_revision(app):
    panel = AlarmPanel()
    try:
        panel.update_v2_status(_wire_payload(engine_instance_id=_ENGINE_A, snapshot_revision=1))
        panel.set_connected(True)
        replacement = AnnunciationRegistry(engine_instance_id=_ENGINE_B)
        replacement.sync({}, {"state": "safe_off", "fault_revision": 0})
        snapshot = replacement.snapshot()
        handler_payload = {
            "ok": True,
            "engine_instance_id": snapshot["engine_instance_id"],
            "snapshot_revision": snapshot["snapshot_revision"],
            "active": {},
            "history": [],
        }

        panel.update_v2_status(_wire_from_handler(handler_payload))

        assert snapshot["snapshot_revision"] == 1
        assert panel._v2_engine_instance_id == _ENGINE_B
        assert panel._v2_snapshot_revision == 1
        assert panel._v2_snapshot_authoritative is True
        assert panel._v2_alarms == {}
    finally:
        _dispose_panel(panel, app)


def test_malformed_nested_snapshot_retains_evidence_and_revokes_ack(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    malformed = _wire_payload(snapshot_revision=2)
    malformed["active"] = {"cold": "not-a-row"}
    panel.update_v2_status(malformed)
    assert set(panel._v2_alarms) == {"cold"}
    assert panel._v2_engine_instance_id == _ENGINE_A
    assert panel._v2_snapshot_revision == 1
    assert panel._v2_snapshot_authoritative is False
    assert not panel._v2_table.cellWidget(0, 5).isEnabled()
    assert "недоступны" in panel._summary_label.text().lower()
    assert "последние" in panel._summary_label.toolTip().lower()
    panel._v2_poll_timer.stop()


def test_malformed_channels_cannot_replace_evidence_or_raise(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    malformed = _payload()
    malformed["snapshot_revision"] = 2
    malformed["active"]["cold"]["channels"] = 7

    panel.update_v2_status(malformed)

    assert panel._v2_alarms["cold"]["channels"] == ["T11"]
    assert panel._v2_snapshot_revision == 1
    assert panel._v2_snapshot_authoritative is False
    assert not panel._v2_table.cellWidget(0, 5).isEnabled()
    panel._v2_poll_timer.stop()


def test_unidentified_empty_snapshot_is_rejected_without_erasing_evidence(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.update_v2_status({"ok": True, "active": {}})
    assert set(panel._v2_alarms) == {"cold"}
    assert panel._v2_snapshot_authoritative is False


@pytest.mark.parametrize(
    "corruption",
    [
        "extra",
        "missing_proto",
        "bool_proto",
        "wrong_proto",
        "short_engine",
        "uppercase_engine",
        "nonhex_engine",
    ],
)
def test_open_or_malformed_empty_snapshot_retains_evidence_and_revokes_ack(app, corruption: str):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    candidate = _payload()
    candidate["snapshot_revision"] = 2
    candidate["active"] = {}
    if corruption == "extra":
        candidate["compat"] = True
    elif corruption == "missing_proto":
        candidate.pop("proto")
    elif corruption == "bool_proto":
        candidate["proto"] = True
    elif corruption == "wrong_proto":
        candidate["proto"] = CLIENT_PROTOCOL_VERSION + 1
    elif corruption == "short_engine":
        candidate["engine_instance_id"] = "short"
    elif corruption == "uppercase_engine":
        candidate["engine_instance_id"] = "A" * 32
    else:
        candidate["engine_instance_id"] = "g" * 32

    panel.update_v2_status(candidate)

    assert set(panel._v2_alarms) == {"cold"}
    assert panel._v2_engine_instance_id == _ENGINE_A
    assert panel._v2_snapshot_revision == 1
    assert panel._v2_snapshot_authoritative is False
    assert not panel._v2_table.cellWidget(0, 5).isEnabled()
    panel._v2_poll_timer.stop()


def test_equal_revision_with_different_active_cut_is_rejected_as_equivocal(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    equivocal = _payload()
    equivocal["active"] = {}

    panel.update_v2_status(equivocal)

    assert set(panel._v2_alarms) == {"cold"}
    assert panel._v2_snapshot_revision == 1
    assert panel._v2_snapshot_authoritative is False
    assert not panel._v2_table.cellWidget(0, 5).isEnabled()
    panel._v2_poll_timer.stop()


def test_long_message_preserves_full_tooltip(app):
    panel = AlarmPanel()
    payload = _payload()
    message = "<b>complete diagnostic evidence</b><img src=x> " * 10
    payload["active"]["cold"]["message"] = message
    panel.update_v2_status(payload)
    item = panel._v2_table.item(0, 2)
    assert item.text().endswith("…")
    assert item.toolTip() == plain_text_tooltip(message)
    assert "<b>" not in item.toolTip()
    assert "<img" not in item.toolTip()
    document = QTextDocument()
    document.setHtml(item.toolTip())
    assert document.toPlainText() == message


def test_disconnect_preserves_rows_and_disables_ack(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    panel.set_connected(False)
    assert panel._v2_table.rowCount() == 1
    assert not panel._v2_table.cellWidget(0, 5).isEnabled()


def test_read_only_rejects_direct_ack_invocation(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    panel.set_read_only(True)
    _StubWorker.dispatched = []
    panel._acknowledge_v2("cold")
    assert _StubWorker.dispatched == []
    panel._v2_poll_timer.stop()


@pytest.mark.parametrize("invalid", [0, 1, None, "true", object()])
def test_live_authority_requires_exact_bool(app, invalid):
    panel = AlarmPanel()
    try:
        with pytest.raises(TypeError, match="live authority must be an exact bool"):
            panel.set_live_authority(invalid)
        assert panel._live_authority is True
    finally:
        _dispose_panel(panel, app)


def test_disabled_live_authority_stops_and_blocks_all_alarm_polls(app):
    panel = AlarmPanel()
    try:
        panel.update_v2_status(_payload())
        panel._update_cooldown_ui("WATCHING", 0.5, 2.0)
        prior_cooldown_text = panel._cooldown_status_lbl.text()
        panel.set_connected(True)
        assert panel._v2_poll_timer.isActive()
        assert panel._cooldown_poll_timer.isActive()

        panel.set_live_authority(False)

        assert panel._live_authority is False
        assert panel._v2_snapshot_authoritative is False
        assert panel._v2_table.rowCount() == 1
        assert not panel._v2_table.cellWidget(0, 5).isEnabled()
        assert not panel._v2_poll_timer.isActive()
        assert not panel._cooldown_poll_timer.isActive()
        assert "live authority disabled" in panel._summary_label.text()
        unavailable_cooldown_text = panel._cooldown_status_lbl.text()
        assert unavailable_cooldown_text != prior_cooldown_text
        assert theme.MUTED_FOREGROUND in panel._cooldown_status_lbl.styleSheet()

        panel._v2_poll_timer.start()
        panel._cooldown_poll_timer.start()
        panel.set_connected(True)
        assert not panel._v2_poll_timer.isActive()
        assert not panel._cooldown_poll_timer.isActive()

        _StubWorker.dispatched = []
        panel._poll_v2_status()
        panel._poll_cooldown_status()
        assert _StubWorker.dispatched == []

        late = _wire_payload(snapshot_revision=2)
        generation = panel._connection_generation
        panel._on_poll_v2_result(late, generation)
        panel.update_v2_status(late)
        panel._on_cooldown_status(
            {"state": "FIRED", "progress": 0.9, "eta_h": 0.5},
            generation=generation,
        )
        assert panel._v2_snapshot_revision == 1
        assert panel._v2_snapshot_authoritative is False
        assert panel._cooldown_status_lbl.text() == unavailable_cooldown_text
    finally:
        _dispose_panel(panel, app)


def test_polling_requires_connection_and_preserves_last_state_on_error(app):
    panel = AlarmPanel()
    panel._poll_v2_status()
    assert _StubWorker.dispatched == []
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    _StubWorker.next_result = {"ok": False, "error": "boom"}
    _StubWorker.dispatched = []
    panel._poll_v2_status()
    assert _StubWorker.dispatched == [{"cmd": "alarm_v2_status"}]
    assert set(panel._v2_alarms) == {"cold"}
    assert panel._v2_snapshot_authoritative is False
    assert not panel._v2_table.cellWidget(0, 5).isEnabled()
    panel._v2_poll_timer.stop()


def test_late_poll_reply_after_disconnect_cannot_restore_authority(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    old_generation = panel._connection_generation
    panel.set_connected(False)
    late = _payload()
    late["snapshot_revision"] = 2

    panel._on_poll_v2_result(late, old_generation)

    assert panel._v2_snapshot_revision == 1
    assert panel._v2_snapshot_authoritative is False


def test_late_poll_reply_after_reconnect_cannot_cross_generation(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    old_generation = panel._connection_generation
    panel.set_connected(False)
    panel.set_connected(True)
    late = _payload()
    late["snapshot_revision"] = 2

    panel._on_poll_v2_result(late, old_generation)

    assert panel._v2_snapshot_revision == 1
    assert panel._v2_snapshot_authoritative is False
    panel._v2_poll_timer.stop()


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(45.0, "45 с"), (120.0, "2 мин"), (3660.0, "1.0 ч")],
)
def test_elapsed_text(seconds, expected):
    assert _elapsed_text(seconds) == expected


def test_complete_live_empty_snapshot_restores_explicit_empty_state(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.update_v2_status(_wire_payload(snapshot_revision=2, active={}))
    assert panel._v2_snapshot_authoritative is True
    assert panel._body_stack.currentWidget() is panel._body_empty_page
    labels = panel._body_empty_page.findChildren(QLabel)
    assert any("Нет активных тревог" in label.text() for label in labels)
    assert not any("недоступ" in label.text().casefold() for label in labels)


def test_cooldown_completion_is_phase_evidence_not_green_health(app):
    panel = AlarmPanel()
    panel._update_cooldown_ui("AUTO_DISARMED", 1.0, 0.0)
    assert panel._cooldown_status_lbl.text() == "Захолаживание завершено"
    assert theme.ACCENT in panel._cooldown_status_lbl.styleSheet()
    assert theme.STATUS_OK not in panel._cooldown_status_lbl.styleSheet()


def test_unknown_cooldown_state_is_explicit_and_neutral(app):
    panel = AlarmPanel()
    panel._update_cooldown_ui("NEW_BACKEND_STATE", None, None)
    assert panel._cooldown_status_lbl.text() == "Неизвестное состояние: NEW_BACKEND_STATE"
    assert theme.MUTED_FOREGROUND in panel._cooldown_status_lbl.styleSheet()
