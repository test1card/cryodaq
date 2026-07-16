"""Focused contract tests for the authoritative phase-aware alarm overlay."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.alarm_panel import (
    AlarmPanel,
    SeverityChip,
    _elapsed_text,
    _make_ack_button,
)


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

    def __init__(self, cmd, *, parent=None) -> None:
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


def _payload(*, acknowledged: bool = False) -> dict:
    return {
        "ok": True,
        "engine_instance_id": "engine-a",
        "snapshot_revision": 1,
        "active": {
            "cold": {
                "level": "CRITICAL",
                "activation_id": "activation-a",
                "message": "plate hot",
                "channels": ["T11"],
                "triggered_at": time.time() - 10,
                "acknowledged": acknowledged,
            }
        },
    }


def test_panel_is_v2_only_and_empty_by_default(app):
    panel = AlarmPanel()
    assert panel.objectName() == "alarmPanel"
    assert panel._v2_alarms == {}
    assert panel._v2_table.columnCount() == 6
    assert not hasattr(panel, "_table")
    assert not hasattr(panel, "on_reading")
    assert not hasattr(panel, "get_active_v1_count")
    assert panel._body_stack.currentWidget() is panel._body_empty_page


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


def test_acknowledged_alarm_stays_visible_but_leaves_attention_count(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload(acknowledged=True))
    assert panel.get_active_v2_count() == 0
    assert panel._v2_table.rowCount() == 1
    assert panel._v2_table.cellWidget(0, 5) is None
    assert panel._v2_table.item(0, 5).text() == "Подтв."
    chip = panel._v2_table.cellWidget(0, 0)
    assert isinstance(chip, SeverityChip)
    assert "✓" in chip.text()


def test_exact_activation_ack_dispatches_captured_identity(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    _StubWorker.dispatched = []
    button = panel._v2_table.cellWidget(0, 5)
    assert isinstance(button, QPushButton)
    assert button.isEnabled()
    button.click()
    assert _StubWorker.dispatched == [
        {
            "cmd": "alarm_v2_ack",
            "alarm_name": "cold",
            "engine_instance_id": "engine-a",
            "activation_id": "activation-a",
            "operator": "",
            "reason": "",
        }
    ]
    panel._v2_poll_timer.stop()


def test_missing_exact_identity_keeps_evidence_but_disables_ack(app):
    panel = AlarmPanel()
    panel.update_v2_status({"ok": True, "active": {"cold": {"level": "CRITICAL"}}})
    panel.set_connected(True)
    assert panel._v2_table.rowCount() == 0
    assert "недоступны" in panel._summary_label.text().lower()
    panel._v2_poll_timer.stop()


def test_delayed_button_keeps_old_activation_identity(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    old_button = panel._v2_table.cellWidget(0, 5)
    newer = _payload()
    newer["snapshot_revision"] = 2
    newer["active"]["cold"]["activation_id"] = "activation-b"
    panel.update_v2_status(newer)
    _StubWorker.dispatched = []
    old_button.click()
    assert _StubWorker.dispatched[0]["activation_id"] == "activation-a"
    panel._v2_poll_timer.stop()


def test_out_of_order_same_engine_snapshot_is_ignored(app):
    panel = AlarmPanel()
    current = _payload()
    current["snapshot_revision"] = 2
    panel.update_v2_status(current)
    stale = _payload()
    stale["snapshot_revision"] = 1
    stale["active"] = {"old": {"level": "CRITICAL", "activation_id": "old"}}
    panel.update_v2_status(stale)
    assert set(panel._v2_alarms) == {"cold"}
    assert panel._v2_snapshot_revision == 2


def test_malformed_nested_snapshot_retains_evidence_and_revokes_ack(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.set_connected(True)
    malformed = {
        "ok": True,
        "engine_instance_id": "engine-a",
        "snapshot_revision": 2,
        "active": {"cold": "not-a-row"},
    }
    panel.update_v2_status(malformed)
    assert set(panel._v2_alarms) == {"cold"}
    assert panel._v2_engine_instance_id == "engine-a"
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


def test_long_message_preserves_full_tooltip(app):
    panel = AlarmPanel()
    payload = _payload()
    message = "complete diagnostic evidence " * 10
    payload["active"]["cold"]["message"] = message
    panel.update_v2_status(payload)
    item = panel._v2_table.item(0, 2)
    assert item.text().endswith("…")
    assert item.toolTip() == message


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


def test_empty_payload_restores_explicit_empty_state(app):
    panel = AlarmPanel()
    panel.update_v2_status(_payload())
    panel.update_v2_status(
        {
            "ok": True,
            "engine_instance_id": "engine-a",
            "snapshot_revision": 2,
            "active": {},
        }
    )
    assert panel._body_stack.currentWidget() is panel._body_empty_page
    labels = panel._body_empty_page.findChildren(QLabel)
    assert any("Нет активных тревог" in label.text() for label in labels)


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
