"""Tests for shift handover widgets."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from cryodaq.gui.widgets.shift_handover import (
    ShiftBar,
    ShiftEndDialog,
    ShiftPeriodicPrompt,
    ShiftStartDialog,
    load_shift_config,
    _shift_id,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def test_load_shift_config_returns_dict() -> None:
    config = load_shift_config()
    assert isinstance(config, dict)


def test_shift_id_format() -> None:
    sid = _shift_id()
    assert sid.startswith("shift-")
    parts = sid.split("-")
    assert len(parts) == 3
    assert len(parts[1]) == 8  # date
    assert len(parts[2]) == 2  # hour


# ---------------------------------------------------------------------------
# ShiftStartDialog
# ---------------------------------------------------------------------------

def test_shift_start_dialog_creates_with_operators() -> None:
    _app()
    config = {"operators": ["Фоменко В.Н.", "Иванов А.А."]}
    dialog = ShiftStartDialog(config)

    assert dialog._operator_combo.count() == 2
    assert dialog._operator_combo.itemText(0) == "Фоменко В.Н."
    assert not dialog._start_btn.isEnabled()


def test_shift_start_dialog_accepts_with_operator() -> None:
    _app()
    config = {"operators": ["Фоменко В.Н."]}
    dialog = ShiftStartDialog(config)

    dialog._checks = [{"name": "test", "ok": True, "detail": "OK"}]
    dialog._start_btn.setEnabled(True)

    received = []
    dialog.shift_started.connect(lambda op, sid: received.append((op, sid)))

    with patch("cryodaq.gui.zmq_client.send_command", return_value={"ok": True}):
        dialog._operator_combo.setCurrentText("Фоменко В.Н.")
        dialog._on_accept()

    assert len(received) == 1
    assert received[0][0] == "Фоменко В.Н."
    assert received[0][1].startswith("shift-")


# ---------------------------------------------------------------------------
# ShiftPeriodicPrompt
# ---------------------------------------------------------------------------

def test_periodic_prompt_submits_log_entry() -> None:
    _app()
    dialog = ShiftPeriodicPrompt(
        operator="Фоменко В.Н.",
        shift_id="shift-20260317-08",
    )
    dialog._status_combo.setCurrentText("Штатно")
    dialog._notes.setPlainText("Всё в порядке")

    with patch("cryodaq.gui.zmq_client.send_command", return_value={"ok": True}) as mock_cmd:
        dialog._on_submit()

    mock_cmd.assert_called_once()
    call_args = mock_cmd.call_args[0][0]
    assert call_args["cmd"] == "log_entry"
    assert "shift_periodic" in call_args["tags"]
    assert "Штатно" in call_args["message"]
    assert call_args["author"] == "Фоменко В.Н."


# ---------------------------------------------------------------------------
# ShiftEndDialog
# ---------------------------------------------------------------------------

def test_shift_end_dialog_generates_summary() -> None:
    _app()
    import time

    start = time.monotonic() - 7200  # 2 hours ago
    dialog = ShiftEndDialog(
        operator="Фоменко В.Н.",
        shift_id="shift-20260317-08",
        start_time=start,
        periodic_count=3,
        missed_count=1,
    )

    received = []
    dialog.shift_ended.connect(lambda: received.append(True))

    with patch("cryodaq.gui.zmq_client.send_command", return_value={"ok": True}) as mock_cmd:
        dialog._comment.setPlainText("Штатно, система стабильна")
        dialog._on_end()

    mock_cmd.assert_called_once()
    call_args = mock_cmd.call_args[0][0]
    assert call_args["cmd"] == "log_entry"
    assert "shift_end" in call_args["tags"]
    metadata = json.loads(call_args["metadata"])
    assert metadata["periodic_count"] == 3
    assert metadata["missed_count"] == 1
    assert metadata["comment"] == "Штатно, система стабильна"
    assert len(received) == 1


# ---------------------------------------------------------------------------
# ShiftBar
# ---------------------------------------------------------------------------

def test_shift_bar_initializes_inactive() -> None:
    _app()
    bar = ShiftBar()

    assert not bar.is_active
    assert bar.operator_name == ""
    assert "не активна" in bar._status_label.text()
    # In offscreen mode, use isHidden() since parent is not shown
    assert not bar._start_btn.isHidden()
    assert bar._end_btn.isHidden()


def test_shift_bar_activate_deactivate() -> None:
    _app()
    bar = ShiftBar()

    bar._activate_shift("Фоменко В.Н.", "shift-20260317-08")

    assert bar.is_active
    assert bar.operator_name == "Фоменко В.Н."
    assert "Фоменко" in bar._status_label.text()
    assert bar._start_btn.isHidden()
    assert not bar._end_btn.isHidden()

    bar._deactivate_shift()

    assert not bar.is_active
    assert "не активна" in bar._status_label.text()
    assert not bar._start_btn.isHidden()
    assert bar._end_btn.isHidden()
