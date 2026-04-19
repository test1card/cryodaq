"""Tests for shift handover widgets."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock, patch


def _patch_worker_capture():
    """Patch ZmqCommandWorker to capture payloads synchronously instead of
    spawning a thread (Phase 2c baseline cleanup).

    Returns a tuple of (patcher, capture_list). The capture_list collects
    every payload dict passed to the worker constructor — this lets the
    test assert on the dispatched command without running a real Qt thread.
    """
    captured: list[dict] = []

    def _fake_worker(payload, parent=None, **kw):
        captured.append(payload)
        worker = MagicMock()
        worker.start = MagicMock()
        worker.finished = MagicMock()
        worker.finished.connect = MagicMock()
        worker.isRunning = MagicMock(return_value=False)
        worker.deleteLater = MagicMock()
        return worker

    # The widget imports ZmqCommandWorker inside method bodies, so the
    # binding only exists on the source module. Patch there.
    patcher = patch(
        "cryodaq.gui.zmq_client.ZmqCommandWorker",
        side_effect=_fake_worker,
    )
    return patcher, captured


from PySide6.QtWidgets import QApplication  # noqa: E402

from cryodaq.gui.widgets.shift_handover import (  # noqa: E402
    ShiftBar,
    ShiftEndDialog,
    ShiftPeriodicPrompt,
    ShiftStartDialog,
    _shift_id,
    load_shift_config,
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
    """Phase 2c baseline cleanup: shift_handover dispatches via ZmqCommandWorker
    on a Qt thread now (was direct send_command). Patch the worker class
    to capture the payload synchronously instead of waiting on the thread.
    """
    _app()
    dialog = ShiftPeriodicPrompt(
        operator="Фоменко В.Н.",
        shift_id="shift-20260317-08",
    )
    dialog._status_combo.setCurrentText("Штатно")
    dialog._notes.setPlainText("Всё в порядке")

    patcher, captured = _patch_worker_capture()
    with patcher:
        dialog._on_submit()

    assert len(captured) == 1, f"Expected 1 worker dispatch, got {len(captured)}"
    payload = captured[0]
    assert payload["cmd"] == "log_entry"
    assert "shift_periodic" in payload["tags"]
    assert "Штатно" in payload["message"]
    assert payload["author"] == "Фоменко В.Н."


# ---------------------------------------------------------------------------
# ShiftEndDialog
# ---------------------------------------------------------------------------


def test_shift_end_dialog_generates_summary() -> None:
    """IV.4 F11: dialog now dispatches 4 async section queries at open
    time plus the log_entry on save. We patch the worker before the
    constructor fires so both paths go through the capture list, then
    filter to the log_entry payload for the save assertion."""
    _app()
    import time

    start = time.monotonic() - 7200  # 2 hours ago
    patcher, captured = _patch_worker_capture()
    with patcher:
        dialog = ShiftEndDialog(
            operator="Фоменко В.Н.",
            shift_id="shift-20260317-08",
            start_time=start,
            periodic_count=3,
            missed_count=1,
        )

        received = []
        dialog.shift_ended.connect(lambda: received.append(True))

        dialog._comment.setPlainText("Штатно, система стабильна")
        dialog._on_end()

    log_entries = [p for p in captured if p.get("cmd") == "log_entry"]
    assert len(log_entries) == 1
    payload = log_entries[0]
    assert "shift_end" in payload["tags"]
    metadata = json.loads(payload["metadata"])
    assert metadata["periodic_count"] == 3
    assert metadata["missed_count"] == 1
    assert metadata["comment"] == "Штатно, система стабильна"
    assert "markdown_body" in metadata
    assert "Сдача смены" in metadata["markdown_body"]
    assert len(received) == 1


# ---------------------------------------------------------------------------
# IV.4 F11 — shift handover auto-sections
# ---------------------------------------------------------------------------


def test_shift_end_dialog_dispatches_four_section_queries() -> None:
    """On open, dialog dispatches log_get / alarm_v2_history /
    readings_history / experiment_status to populate sections."""
    _app()
    import time

    patcher, captured = _patch_worker_capture()
    with patcher:
        ShiftEndDialog(
            operator="Vladimir",
            shift_id="shift-20260420-10",
            start_time=time.monotonic() - 3600,
            periodic_count=0,
            missed_count=0,
            start_epoch=time.time() - 3600,
        )
    cmds = {p.get("cmd") for p in captured}
    assert {
        "log_get",
        "alarm_v2_history",
        "readings_history",
        "experiment_status",
    }.issubset(cmds)


def test_shift_end_dialog_empty_shift_window_falls_back_to_8h() -> None:
    """No start_epoch provided → dialog uses a 8h window ending now."""
    _app()
    import time

    patcher, _captured = _patch_worker_capture()
    before = time.time()
    with patcher:
        dialog = ShiftEndDialog(
            operator="V",
            shift_id="s",
            start_time=time.monotonic(),
            periodic_count=0,
            missed_count=0,
            start_epoch=None,
        )
    # Window width must be ~8h within a 2s construction-time slack.
    window = dialog._end_epoch - dialog._start_epoch
    assert abs(window - 8 * 3600) < 2.0
    assert dialog._end_epoch >= before


def test_shift_end_dialog_populates_events_section() -> None:
    """Events reply with phase/experiment tags renders as Markdown list."""
    from cryodaq.gui.widgets.shift_handover import format_shift_events_section

    rendered = format_shift_events_section(
        [
            {
                "timestamp": 1_700_000_000,
                "author": "Vladimir",
                "message": "Vacuum phase entered",
                "tags": ["phase"],
            }
        ]
    )
    assert "Vacuum phase entered" in rendered
    assert "phase" in rendered
    assert "Vladimir" in rendered


def test_shift_end_dialog_populates_alarms_section() -> None:
    from cryodaq.gui.widgets.shift_handover import format_shift_alarms_section

    rendered = format_shift_alarms_section(
        [
            {
                "at": 1_700_000_000,
                "transition": "TRIGGERED",
                "level": "CRITICAL",
                "alarm_id": "T_stage_overheat",
                "message": "Cold plate > 5 K",
            },
            {
                "at": 1_700_000_500,
                "transition": "ACKNOWLEDGED",
                "level": "CRITICAL",
                "alarm_id": "T_stage_overheat",
            },
        ]
    )
    assert "T_stage_overheat" in rendered
    assert "TRIGGERED" in rendered
    assert "ACKNOWLEDGED" in rendered


def test_shift_end_dialog_populates_temperatures_section() -> None:
    """min / max / delta rendered as a 4-column Markdown table."""
    from cryodaq.gui.widgets.shift_handover import format_shift_temperatures_section

    rendered = format_shift_temperatures_section(
        {
            "Т1": {"min": 3.97, "max": 290.12},
            "Т2": {"min": 4.03, "max": 289.87},
        }
    )
    assert "Т1" in rendered
    assert "Т2" in rendered
    assert "| Канал" in rendered
    # Delta for Т1 = 290.12 - 3.97 = 286.150
    assert "286.150" in rendered


def test_shift_end_dialog_populates_experiment_progress_section() -> None:
    from cryodaq.gui.widgets.shift_handover import format_shift_experiment_section

    rendered = format_shift_experiment_section(
        {
            "ok": True,
            "active_experiment": {
                "name": "Thermal conductivity run 42",
                "operator": "Vladimir",
            },
            "phases": [
                {"phase": "preparation", "started_at": 0, "ended_at": 1200},
                {"phase": "vacuum", "started_at": 1200, "ended_at": 6000},
                {"phase": "cooldown", "started_at": 6000, "ended_at": 9600},
            ],
        }
    )
    assert "Thermal conductivity run 42" in rendered
    assert "preparation" in rendered
    assert "(20 мин)" in rendered  # preparation duration = 20 min


def test_shift_end_dialog_markdown_export_format() -> None:
    """Markdown export glues sections + metadata in a stable layout."""
    from cryodaq.gui.widgets.shift_handover import compose_shift_handover_markdown

    body = compose_shift_handover_markdown(
        operator="Vladimir",
        start_epoch=1_700_000_000.0,
        end_epoch=1_700_028_800.0,
        events="- событие 1",
        alarms="— тревог не было",
        temperatures="| Канал | ... |",
        experiment="- Эксперимент: **X**",
        comment="все ок",
        handover_note="смотреть Т7",
    )
    assert body.startswith("# Сдача смены — Vladimir")
    assert "## События смены" in body
    assert "## Тревоги за смену" in body
    assert "## Температуры за смену" in body
    assert "## Прогресс эксперимента" in body
    assert "## Комментарии" in body
    assert "## Передача следующему оператору" in body
    assert "все ок" in body
    assert "смотреть Т7" in body


def test_shift_end_dialog_saves_markdown_body_to_operator_log() -> None:
    """_on_end includes the compiled Markdown in the log entry's metadata."""
    _app()
    import time

    patcher, captured = _patch_worker_capture()
    with patcher:
        dialog = ShiftEndDialog(
            operator="Vladimir",
            shift_id="shift-1",
            start_time=time.monotonic(),
            periodic_count=0,
            missed_count=0,
            start_epoch=time.time() - 3600,
        )
        # Simulate replies so the sections have real content.
        dialog._events_section_text = "- 12:00 событие"
        dialog._alarms_section_text = "— тревог не было"
        dialog._temperatures_section_text = "| Канал | ... |"
        dialog._experiment_section_text = "- эксперимент X"
        dialog._on_end()
    log_payloads = [p for p in captured if p.get("cmd") == "log_entry"]
    assert log_payloads
    metadata = json.loads(log_payloads[0]["metadata"])
    assert "markdown_body" in metadata
    assert "событие" in metadata["markdown_body"]
    assert metadata["shift_start_ts"]
    assert metadata["shift_end_ts"]


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
