from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.overview_panel import KeithleyStrip, StatusStrip


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _channel_state_reading(channel: str, state: str) -> Reading:
    return Reading.now(
        channel=f"analytics/keithley_channel_state/{channel}",
        value={"off": 0.0, "on": 1.0, "fault": -1.0}[state],
        unit="",
        instrument_id="safety_manager",
        metadata={"state": state, "channel": channel},
    )


def test_status_strip_accepts_lowercase_safety_state() -> None:
    _app()
    widget = StatusStrip()

    widget.set_safety_state("safe_off")
    assert widget._safety_label.text() == "SAFE_OFF"

    widget.set_safety_state("fault_latched")
    assert widget._safety_label.text() == "FAULT_LATCHED"


def test_keithley_strip_hides_on_lowercase_safe_off() -> None:
    _app()
    widget = KeithleyStrip()
    widget.set_channel_state("smua", "on")
    widget.setVisible(True)

    widget.set_safety_state("safe_off")

    assert not widget.isVisible()


def test_keithley_strip_backend_state_controls_visual_status() -> None:
    _app()
    widget = KeithleyStrip()

    widget.set_channel_state("smua", "on")
    widget.set_channel_state("smub", "fault")

    assert "smua: ВКЛ" in widget._smua_label.text()
    assert "smub: АВАРИЯ" in widget._smub_label.text()


def test_keithley_strip_telemetry_does_not_force_on_state() -> None:
    _app()
    widget = KeithleyStrip()

    widget.on_reading(Reading.now(channel="K1/smua/power", value=1.0, unit="W", instrument_id="K1"))

    assert "smua: ВЫКЛ" in widget._smua_label.text()


def test_keithley_strip_updates_both_channels_independently() -> None:
    _app()
    widget = KeithleyStrip()

    widget.on_reading(Reading.now(channel="K1/smua/power", value=1.0, unit="W", instrument_id="K1"))
    widget.on_reading(Reading.now(channel="K1/smub/power", value=2.0, unit="W", instrument_id="K1"))
    widget.set_channel_state("smua", "on")
    widget.set_channel_state("smub", "on")

    assert "P=1.00" in widget._smua_label.text()
    assert "P=2.00" in widget._smub_label.text()


def test_backend_state_off_controls_visual_off_even_with_nonzero_telemetry() -> None:
    _app()
    widget = KeithleyStrip()

    widget.on_reading(Reading.now(channel="K1/smua/power", value=3.0, unit="W", instrument_id="K1"))
    widget.set_channel_state("smua", "off")

    assert "smua: ВЫКЛ" in widget._smua_label.text()


# ---------------------------------------------------------------------------
# KeithleyStrip quick-action buttons
# ---------------------------------------------------------------------------


def test_keithley_strip_is_monitoring_only() -> None:
    """KeithleyStrip is for monitoring — no start/stop buttons (removed in v0.13)."""
    _app()
    widget = KeithleyStrip()
    # Quick-action methods removed — overview is monitoring only
    assert not hasattr(widget, "_on_quick_start")
    assert not hasattr(widget, "_on_quick_stop")
    assert not hasattr(widget, "_on_emergency_off")


# ---------------------------------------------------------------------------
# ExperimentStatusWidget
# ---------------------------------------------------------------------------


def test_experiment_status_widget_initializes() -> None:
    _app()
    from cryodaq.gui.widgets.overview_panel import ExperimentStatusWidget

    widget = ExperimentStatusWidget()
    assert "Нет активного эксперимента" in widget._status_label.text()
    assert widget._elapsed_label.text() == ""


# ---------------------------------------------------------------------------
# QuickLogWidget
# ---------------------------------------------------------------------------


def test_quick_log_widget_initializes() -> None:
    _app()
    from cryodaq.gui.widgets.overview_panel import QuickLogWidget

    widget = QuickLogWidget()
    assert widget._input.text() == ""
    assert widget._input.placeholderText() == "Заметка оператора..."


def test_quick_log_widget_renders_only_first_line_of_multiline_message() -> None:
    """IV.4 F11: shift_end log entries embed a full Markdown body in the
    message field. The compact recent-logs widget must render only the
    first line so it doesn't dump the Markdown summary into its label."""
    _app()
    from cryodaq.gui.widgets.overview_panel import QuickLogWidget

    widget = QuickLogWidget()
    widget._on_refresh_result(
        {
            "ok": True,
            "entries": [
                {
                    "timestamp": "2026-04-20T12:00:00",
                    "message": (
                        "Сдача смены: Vladimir | OK\n\n"
                        "# Сдача смены — Vladimir\nsection body"
                    ),
                }
            ],
        }
    )
    rendered = widget._recent_label.text()
    assert "Сдача смены: Vladimir | OK" in rendered
    # Markdown body must not leak into the compact widget.
    assert "# Сдача смены" not in rendered
    assert "section body" not in rendered


# ---------------------------------------------------------------------------
# CompactTempCard click-toggle
# ---------------------------------------------------------------------------


def test_compact_temp_card_emits_toggled_signal() -> None:
    _app()
    from cryodaq.gui.widgets.overview_panel import CompactTempCard

    card = CompactTempCard("Т1", "Stage A")
    received = []
    card.toggled.connect(lambda ch: received.append(ch))

    card.mousePressEvent(None)

    assert received == ["Т1"]


def test_compact_temp_card_set_active_changes_opacity() -> None:
    _app()
    from cryodaq.gui.widgets.overview_panel import CompactTempCard

    card = CompactTempCard("Т1", "Stage A")
    assert card._active is True

    card.set_active(False)
    assert card._active is False
    effect = card.graphicsEffect()
    assert effect is not None
    assert effect.opacity() < 0.5

    card.set_active(True)
    effect = card.graphicsEffect()
    assert effect.opacity() > 0.9
