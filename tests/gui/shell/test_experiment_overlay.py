"""Tests for ExperimentOverlay (B.8.0.2 rebuild)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from cryodaq.gui.shell.experiment_overlay import ExperimentOverlay


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_overlay_renders_experiment_data(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {
            "name": "Cooldown #5",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "app_mode": "experiment",
            "experiment_id": "exp001",
            "template_id": "custom",
        },
        phase_history=[],
    )
    labels = overlay.findChildren(QLabel)
    texts = " ".join(lbl.text() for lbl in labels)
    assert "Cooldown #5" in texts


def test_overlay_phase_pills_show_duration(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {
            "name": "E",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "current_phase": "cooldown",
            "experiment_id": "e1",
            "template_id": "custom",
        },
        phase_history=[
            {
                "phase": "preparation",
                "started_at": "2026-04-15T10:00:00+00:00",
                "ended_at": "2026-04-15T10:18:00+00:00",
            },
            {
                "phase": "vacuum",
                "started_at": "2026-04-15T10:18:00+00:00",
                "ended_at": "2026-04-15T12:30:00+00:00",
            },
            {"phase": "cooldown", "started_at": "2026-04-15T12:30:00+00:00", "ended_at": None},
        ],
    )
    labels = overlay.findChildren(QLabel)
    texts = " ".join(lbl.text() for lbl in labels)
    assert "18" in texts  # preparation 18m
    assert "2\u0447" in texts  # vacuum ~2h


def test_overlay_editable_name_validates(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {
            "name": "Original",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "experiment_id": "e1",
            "template_id": "custom",
        },
        phase_history=[],
    )
    overlay._enter_name_edit()
    overlay._name_edit.setText("   ")
    overlay._commit_name_edit()
    assert overlay._displayed_name() == "Original"


def test_overlay_esc_emits_closed(app):
    overlay = ExperimentOverlay()
    received = []
    overlay.closed.connect(lambda: received.append(True))

    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    overlay.keyPressEvent(event)
    assert received == [True]


def test_overlay_no_experiment_disables_finalize(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(None)
    assert not overlay._finalize_btn.isEnabled()


def test_overlay_card_save_payload(app, monkeypatch):
    """Click Save button with a stubbed ZmqCommandWorker; assert command payload."""
    import cryodaq.gui.zmq_client as _zmq_mod

    sent_payloads: list[dict] = []

    class _StubWorker:
        """Captures payload without starting a real thread."""

        def __init__(self, payload: dict, parent=None):
            sent_payloads.append(payload)

        @property
        def finished(self):
            return self

        def connect(self, *args):
            pass

        def start(self):
            pass

    monkeypatch.setattr(_zmq_mod, "ZmqCommandWorker", _StubWorker)

    overlay = ExperimentOverlay()
    overlay.set_connected(True)
    overlay.set_experiment(
        {
            "name": "E",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "experiment_id": "e1",
            "template_id": "custom",
            "sample": "S",
            "description": "D",
            "notes": "N",
        },
        phase_history=[],
    )
    overlay._sample_edit.setText("NewSample")
    # Clear payloads accumulated by set_experiment (e.g. log_get timeline load).
    sent_payloads.clear()
    # Click the real Save button — triggers _on_save_card → _build_card_payload → worker.
    overlay._save_btn.click()

    update_cmds = [p for p in sent_payloads if p.get("cmd") == "experiment_update"]
    assert len(update_cmds) == 1, f"expected 1 experiment_update ZMQ command, got {sent_payloads!r}"
    payload = update_cmds[0]
    assert payload["sample"] == "NewSample"
    assert payload["experiment_id"] == "e1"
    assert "custom_fields" in payload


def test_overlay_abort_in_more_menu(app, monkeypatch):
    """Abort lives in the ⋯ More menu, not the footer.

    Assert: (1) no visible abort button in footer;
            (2) _on_abort_clicked fires the experiment_abort ZMQ command.
    """
    import unittest.mock as mock

    from PySide6.QtWidgets import QMessageBox, QPushButton

    import cryodaq.gui.zmq_client as _zmq_mod

    sent_payloads: list[dict] = []

    class _StubWorker:
        def __init__(self, payload: dict, parent=None):
            sent_payloads.append(payload)

        @property
        def finished(self):
            return self

        def connect(self, *args):
            pass

        def start(self):
            pass

    monkeypatch.setattr(_zmq_mod, "ZmqCommandWorker", _StubWorker)

    overlay = ExperimentOverlay()
    overlay.set_connected(True)
    overlay.set_experiment(
        {
            "name": "E",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "experiment_id": "e1",
            "template_id": "custom",
        },
        [],
    )

    # 1. Abort must NOT appear as a visible footer button.
    buttons = overlay.findChildren(QPushButton)
    visible_abort = [
        b
        for b in buttons
        if "Прервать" in b.text() and not b.isHidden()
    ]
    assert len(visible_abort) == 0, "abort button must not be visible in footer"

    # 2. Trigger abort via the handler the More-menu action calls.
    # Auto-dismiss confirmation dialog: patch exec + clickedButton so cancel branch skipped.
    with mock.patch.object(QMessageBox, "exec", return_value=None):
        with mock.patch.object(QMessageBox, "clickedButton", return_value=None):
            overlay._on_abort_clicked()

    abort_cmds = [p for p in sent_payloads if p.get("cmd") == "experiment_abort"]
    assert len(abort_cmds) == 1, (
        f"expected 1 experiment_abort ZMQ command, got: {sent_payloads!r}"
    )
    assert abort_cmds[0]["experiment_id"] == "e1"


# ----------------------------------------------------------------------
# Batch B regression guards
# ----------------------------------------------------------------------


def _set_phase(overlay: ExperimentOverlay, phase: str) -> None:
    overlay.set_experiment(
        {
            "name": "T",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "current_phase": phase,
            "experiment_id": "e1",
            "template_id": "custom",
        },
        phase_history=[],
    )


def test_phase_labels_are_full_russian_names(app):
    """Regression (Batch B commit 1850482): phase pills render canonical
    full names (PHASE_LABELS_RU), not the 3-letter PHASE_LABELS_PILL
    abbreviations. Guards against a future refactor re-truncating them.
    """
    from cryodaq.core.phase_labels import PHASE_LABELS_RU, PHASE_ORDER

    overlay = ExperimentOverlay()
    for idx, phase in enumerate(PHASE_ORDER):
        pill = overlay._phase_pills[phase]
        label = pill.findChild(QLabel, f"expPillLabel_{phase}")
        assert label is not None, f"pill for {phase} missing full-name label"
        expected = PHASE_LABELS_RU[phase]
        assert label.text() == expected, (
            f"pill {phase}: expected '{expected}', got '{label.text()}'"
        )
        # No ellipsis — full canonical name must appear verbatim.
        assert "\u2026" not in label.text()
        # Numbered prefix is the reading-order index (1..6, no leading zero).
        num_label = pill.findChild(QLabel)  # first QLabel in layout is num
        assert num_label is not None
        # num label appears before the full label in the QVBoxLayout —
        # walk the layout to grab the numeric one explicitly.
        num_widget = pill.layout().itemAt(0).widget()
        assert num_widget.text() == str(idx + 1)


def test_nav_buttons_hidden_when_unavailable(app):
    """Regression (Batch B commit 2d6edc7): _prev_btn / _next_btn use
    setVisible() (not setEnabled(False)) so no dead grey rectangle
    renders on the first / last phase. Uses isHidden() because in
    offscreen Qt child.isVisible() reports False until the top-level
    window is shown.
    """
    from cryodaq.core.phase_labels import PHASE_ORDER

    overlay = ExperimentOverlay()

    _set_phase(overlay, PHASE_ORDER[0])
    assert overlay._prev_btn.isHidden(), "prev button must be hidden on first phase"
    assert not overlay._next_btn.isHidden(), "next button must be visible on first phase"

    _set_phase(overlay, PHASE_ORDER[2])
    assert not overlay._prev_btn.isHidden(), "prev button must be visible in middle"
    assert not overlay._next_btn.isHidden(), "next button must be visible in middle"

    _set_phase(overlay, PHASE_ORDER[-1])
    assert not overlay._prev_btn.isHidden(), "prev button must be visible on last phase"
    assert overlay._next_btn.isHidden(), "next button must be hidden on last phase"


# ----------------------------------------------------------------------
# Phase II.9: set_connected Host Integration Contract
# ----------------------------------------------------------------------


def test_set_connected_default_true(app):
    overlay = ExperimentOverlay()
    # Default keeps actions functional until host pushes the first tick.
    assert overlay._connected is True


def test_set_connected_false_disables_finalize_when_active(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {
            "name": "E",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "experiment_id": "e1",
            "template_id": "custom",
        },
        phase_history=[],
    )
    overlay.set_connected(False)
    assert overlay._finalize_btn.isEnabled() is False


def test_set_connected_false_disables_save_btn(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {
            "name": "E",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "experiment_id": "e1",
            "template_id": "custom",
        },
        phase_history=[],
    )
    overlay.set_connected(False)
    assert overlay._save_btn.isEnabled() is False


def test_set_connected_false_disables_nav_buttons(app):
    overlay = ExperimentOverlay()
    overlay.set_connected(False)
    assert overlay._prev_btn.isEnabled() is False
    assert overlay._next_btn.isEnabled() is False


def test_set_connected_reconnect_restores_finalize(app):
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {
            "name": "E",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "experiment_id": "e1",
            "template_id": "custom",
        },
        phase_history=[],
    )
    overlay.set_connected(False)
    overlay.set_connected(True)
    assert overlay._finalize_btn.isEnabled() is True


def test_set_connected_idempotent(app):
    overlay = ExperimentOverlay()
    overlay.set_connected(True)  # already True
    overlay.set_connected(True)
    assert overlay._connected is True


def test_save_result_respects_connection_gate(app):
    """II.9 Codex fix: _on_save_result must not re-enable the save
    button if the host disconnected while the save was in flight."""
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {
            "name": "E",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "experiment_id": "e1",
            "template_id": "custom",
        },
        phase_history=[],
    )
    overlay.set_connected(False)
    # Simulate: host disconnects mid-save. Worker completes.
    overlay._on_save_result({"ok": True})
    assert overlay._save_btn.isEnabled() is False


def test_finalize_result_respects_connection_gate(app):
    """II.9 Codex fix: _on_finalize_result must not re-enable the
    finalize button if the host disconnected mid-command."""
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {
            "name": "E",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "experiment_id": "e1",
            "template_id": "custom",
        },
        phase_history=[],
    )
    overlay.set_connected(False)
    overlay._on_finalize_result({"ok": False, "error": "disconnected"})
    assert overlay._finalize_btn.isEnabled() is False


def test_save_result_reenables_when_connected(app):
    """Positive-path regression: when host stays connected, completion
    handler must still restore the button."""
    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {
            "name": "E",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "experiment_id": "e1",
            "template_id": "custom",
        },
        phase_history=[],
    )
    # Disabled by save in flight.
    overlay._save_btn.setEnabled(False)
    overlay._on_save_result({"ok": True})
    assert overlay._save_btn.isEnabled() is True


def test_refresh_display_respects_connection_state(app):
    overlay = ExperimentOverlay()
    overlay.set_connected(False)
    overlay.set_experiment(
        {
            "name": "E",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "experiment_id": "e1",
            "template_id": "custom",
        },
        phase_history=[],
    )
    # Refresh re-applies the connection gate.
    assert overlay._finalize_btn.isEnabled() is False


# ----------------------------------------------------------------------
# Phase III.D Item 9 + Item 11 polish
# ----------------------------------------------------------------------


def test_finalize_button_uses_accent_not_status_fault(app):
    """Item 9: «Завершить эксперимент» is the normal concluding
    action, not a destructive abort. Styled ACCENT (primary), not
    STATUS_FAULT (reserved for abort/discard)."""
    from cryodaq.gui import theme

    overlay = ExperimentOverlay()
    ss = overlay._finalize_btn.styleSheet()
    assert theme.ACCENT in ss
    assert theme.ON_ACCENT in ss
    assert theme.STATUS_FAULT not in ss


def test_format_time_same_day_returns_hh_mm(app, monkeypatch):
    """Item 11: same calendar day timeline entry uses HH:MM only.

    Freeze datetime.now in the experiment_overlay module to a fixed noon
    so the test is immune to midnight boundary and wall-clock drift.
    """
    from datetime import UTC, datetime

    import cryodaq.gui.shell.experiment_overlay as _eo_mod

    # Fixed "now": 2026-06-15 12:00:00 UTC
    frozen_now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    # Entry is from the same day at 09:30
    same_day = datetime(2026, 6, 15, 9, 30, 0, tzinfo=UTC)

    real_datetime = _eo_mod.datetime

    class _FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return frozen_now.astimezone(tz) if tz else frozen_now

    monkeypatch.setattr(_eo_mod, "datetime", _FrozenDatetime)
    try:
        text = ExperimentOverlay._format_time(same_day.isoformat())
    finally:
        monkeypatch.setattr(_eo_mod, "datetime", real_datetime)

    assert len(text) == 5, f"same-day format should be HH:MM (5 chars), got {text!r}"
    assert text[2] == ":", f"separator must be ':', got {text!r}"
    assert text == "09:30"


def test_format_time_yesterday_prefixed(app, monkeypatch):
    """Item 11: yesterday's entries prefixed with «вчера».

    Freeze datetime.now so «yesterday» is deterministic.
    """
    from datetime import UTC, datetime

    import cryodaq.gui.shell.experiment_overlay as _eo_mod

    frozen_now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    yesterday_ts = datetime(2026, 6, 14, 15, 45, 0, tzinfo=UTC)

    real_datetime = _eo_mod.datetime

    class _FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return frozen_now.astimezone(tz) if tz else frozen_now

    monkeypatch.setattr(_eo_mod, "datetime", _FrozenDatetime)
    try:
        text = ExperimentOverlay._format_time(yesterday_ts.isoformat())
    finally:
        monkeypatch.setattr(_eo_mod, "datetime", real_datetime)

    assert text.startswith("вчера "), f"yesterday format should start with 'вчера ', got {text!r}"
    assert text == "вчера 15:45"


def test_format_time_older_than_yesterday_shows_date(app, monkeypatch):
    """Item 11: entries older than yesterday show DD.MM prefix.

    Freeze datetime.now so «5 days ago» is deterministic.
    """
    from datetime import UTC, datetime

    import cryodaq.gui.shell.experiment_overlay as _eo_mod

    frozen_now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    old_ts = datetime(2026, 6, 10, 8, 0, 0, tzinfo=UTC)

    real_datetime = _eo_mod.datetime

    class _FrozenDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return frozen_now.astimezone(tz) if tz else frozen_now

    monkeypatch.setattr(_eo_mod, "datetime", _FrozenDatetime)
    try:
        text = ExperimentOverlay._format_time(old_ts.isoformat())
    finally:
        monkeypatch.setattr(_eo_mod, "datetime", real_datetime)

    # Format "DD.MM HH:MM" — 11 chars total.
    assert len(text) == 11, f"older format should be DD.MM HH:MM (11 chars), got {text!r}"
    assert text[2] == "." and text[5] == " " and text[8] == ":", (
        f"format separators wrong in {text!r}"
    )
    assert text == "10.06 08:00"


def test_no_close_button_on_experiment_overlay(app):
    """Regression (Batch B commit b0b460b): the × close button was removed
    because ExperimentOverlay is a primary view, not a modal overlay.
    Operator navigates away via ToolRail / ESC. Guards against the
    × button being re-added in a future refactor.
    """
    from PySide6.QtWidgets import QPushButton

    overlay = ExperimentOverlay()
    for btn in overlay.findChildren(QPushButton):
        assert btn.text() != "\u2715", (
            f"× close button still present (objectName={btn.objectName()!r})"
        )
        assert "close" not in btn.objectName().lower(), (
            f"close-named button still present: {btn.objectName()!r}"
        )
    assert not hasattr(overlay, "_close_btn"), (
        "_close_btn attribute re-introduced on ExperimentOverlay"
    )


def test_landing_page_visible_on_empty_overlay(app):
    """IV.2 B.1 — fresh overlay (no active experiment) shows landing page."""
    overlay = ExperimentOverlay()
    assert overlay._stack.currentWidget() is overlay._landing_page


def test_landing_page_has_create_button(app):
    """Landing page exposes a primary create-experiment CTA."""
    overlay = ExperimentOverlay()
    btn = overlay._landing_create_btn
    assert btn is not None
    assert btn.text().startswith("Создать")


def test_landing_page_text_mentions_required_action(app):
    """Landing body must name the required operator action (create)."""
    overlay = ExperimentOverlay()
    body = overlay._landing_page.findChild(QLabel, "expLandingBody")
    assert body is not None
    text = body.text()
    assert "карточка" in text.lower() or "эксперимента" in text.lower()
    assert "шаблон" in text.lower() or "параметры" in text.lower()


def test_create_button_click_emits_signal(app):
    """Clicking the landing CTA fires experiment_create_requested."""
    overlay = ExperimentOverlay()
    received: list[None] = []
    overlay.experiment_create_requested.connect(lambda: received.append(None))
    overlay._landing_create_btn.click()
    assert len(received) == 1


def test_stack_switches_to_content_page_on_set_experiment(app):
    """Live experiment → content page; None → landing."""
    overlay = ExperimentOverlay()
    assert overlay._stack.currentWidget() is overlay._landing_page
    overlay.set_experiment(
        {
            "name": "E1",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "current_phase": "cooldown",
            "experiment_id": "e1",
            "template_id": "custom",
        }
    )
    assert overlay._stack.currentWidget() is overlay._content_page
    # And back to landing on finalize (experiment becomes None).
    overlay.set_experiment(None)
    assert overlay._stack.currentWidget() is overlay._landing_page


def test_create_button_disabled_when_disconnected(app):
    """Create CTA dispatches a ZMQ command — gate on connection like others."""
    overlay = ExperimentOverlay()
    overlay.set_connected(True)
    assert overlay._landing_create_btn.isEnabled() is True
    overlay.set_connected(False)
    assert overlay._landing_create_btn.isEnabled() is False


def test_current_phase_pill_uses_accent_not_status_ok(app, monkeypatch):
    """IV.2 B.2 — phase pill current-state tier is ACCENT (UI activation),
    not STATUS_OK (reserved for safety/running-status).

    Monkeypatch ACCENT and STATUS_OK to distinct sentinel hex values so the
    assertion is never vacuously skipped when they happen to be equal.
    """
    import cryodaq.gui.shell.experiment_overlay as _eo_mod  # noqa: F401
    import cryodaq.gui.theme as _theme_mod

    _SENTINEL_ACCENT = "#aabbcc"
    _SENTINEL_STATUS_OK = "#001122"

    monkeypatch.setattr(_theme_mod, "ACCENT", _SENTINEL_ACCENT)
    monkeypatch.setattr(_theme_mod, "STATUS_OK", _SENTINEL_STATUS_OK)
    # experiment_overlay imports from theme at module level; patch there too.
    import cryodaq.gui.shell.experiment_overlay as _eo
    if hasattr(_eo, "theme"):
        monkeypatch.setattr(_eo.theme, "ACCENT", _SENTINEL_ACCENT)
        monkeypatch.setattr(_eo.theme, "STATUS_OK", _SENTINEL_STATUS_OK)

    overlay = ExperimentOverlay()
    overlay.set_experiment(
        {
            "name": "E",
            "operator": "V",
            "start_time": "2026-04-15T10:00:00+00:00",
            "current_phase": "cooldown",
            "experiment_id": "e1",
            "template_id": "custom",
        },
        phase_history=[],
    )
    ss = overlay._phase_pills["cooldown"].styleSheet()
    assert _SENTINEL_ACCENT in ss, (
        f"current phase pill missing ACCENT sentinel {_SENTINEL_ACCENT!r}: {ss!r}"
    )
    assert _SENTINEL_STATUS_OK not in ss, (
        f"current phase pill leaked STATUS_OK sentinel {_SENTINEL_STATUS_OK!r} "
        f"(reserved for safety): {ss!r}"
    )
