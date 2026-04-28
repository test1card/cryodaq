"""CooldownHistoryWidget — unit tests (F3-Cycle3, spec §4.2).

Covers acceptance criteria:
1. Widget fetches cooldown_history_get on construction.
2. Result rendered as scatter plot of durations.
3. Empty state handled (no past cooldowns).
4. Error state handled (engine failure → banner, no crash).
5. Construction without engine connection (ZMQ mocked → graceful empty).
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.views.analytics_widgets import CooldownHistoryWidget
from cryodaq.gui.state.time_window import reset_time_window_controller


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _reset(app):
    reset_time_window_controller()
    yield
    reset_time_window_controller()


def _make_widget() -> CooldownHistoryWidget:
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = CooldownHistoryWidget()
    return w


def _cooldown_entry(
    experiment_id: str = "exp_001",
    duration_hours: float = 6.0,
    cooldown_started_at: str = "2026-04-15T10:30:00+00:00",
) -> dict:
    return {
        "experiment_id": experiment_id,
        "sample_name": "test-sample",
        "started_at": "2026-04-15T10:00:00+00:00",
        "cooldown_started_at": cooldown_started_at,
        "cooldown_ended_at": "2026-04-15T16:30:00+00:00",
        "duration_hours": duration_hours,
        "start_T_kelvin": 295.0,
        "end_T_kelvin": 4.5,
        "phase_transitions": [
            {"phase": "cooldown", "ts": cooldown_started_at},
        ],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────────────────


def test_construction_triggers_zmq_fetch(app):
    """CooldownHistoryWidget must issue cooldown_history_get on construction."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        w = CooldownHistoryWidget()

    mock_cls.assert_called_once()
    cmd = mock_cls.call_args[0][0]
    assert cmd["cmd"] == "cooldown_history_get"
    assert cmd.get("limit", 20) <= 20
    mock_instance.start.assert_called_once()
    assert w._history_worker is mock_instance


def test_construction_worker_has_parent(app):
    """ZmqCommandWorker must be constructed with parent=self (lifecycle safety)."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        w = CooldownHistoryWidget()

    _, kwargs = mock_cls.call_args
    assert kwargs.get("parent") is w


def test_construction_limit_kwarg_forwarded_to_cmd(app):
    """limit constructor kwarg must be forwarded to the ZMQ command payload."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        CooldownHistoryWidget(limit=5)

    cmd = mock_cls.call_args[0][0]
    assert cmd["limit"] == 5


def test_construction_default_limit_is_20(app):
    """Default limit must be 20 when no limit kwarg is passed."""
    with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_cls:
        mock_cls.return_value = MagicMock()
        CooldownHistoryWidget()

    cmd = mock_cls.call_args[0][0]
    assert cmd["limit"] == 20


def test_construction_empty_state_visible(app):
    """Fresh widget with no data must show empty-state label and hide the plot."""
    w = _make_widget()
    assert not w._empty_label.isHidden()
    assert w._plot.isHidden()


# ──────────────────────────────────────────────────────────────────────────────
# Empty result
# ──────────────────────────────────────────────────────────────────────────────


def test_empty_cooldowns_shows_empty_state(app):
    """ok=True but empty list → empty-state label stays visible."""
    w = _make_widget()
    w._on_history_loaded({"ok": True, "cooldowns": []})
    assert not w._empty_label.isHidden()
    assert w._plot.isHidden()
    assert w._cooldowns == []


# ──────────────────────────────────────────────────────────────────────────────
# Single result
# ──────────────────────────────────────────────────────────────────────────────


def test_one_cooldown_populates_scatter(app):
    """N=1 cooldown entry must populate the scatter and show the plot."""
    w = _make_widget()
    w._on_history_loaded({"ok": True, "cooldowns": [_cooldown_entry()]})

    assert not w._plot.isHidden()
    assert w._empty_label.isHidden()
    xs, ys = w._scatter.getData()
    assert xs is not None and len(xs) == 1
    assert ys[0] == pytest.approx(6.0)
    assert len(w._cooldowns) == 1


# ──────────────────────────────────────────────────────────────────────────────
# N=20 result
# ──────────────────────────────────────────────────────────────────────────────


def test_twenty_cooldowns_all_rendered(app):
    """N=20 cooldown entries must all appear in the scatter."""
    w = _make_widget()
    entries = [
        _cooldown_entry(
            experiment_id=f"exp_{i:03d}",
            duration_hours=float(i + 1),
            cooldown_started_at=f"2026-04-{i + 1:02d}T10:30:00+00:00",
        )
        for i in range(20)
    ]
    w._on_history_loaded({"ok": True, "cooldowns": entries})

    xs, ys = w._scatter.getData()
    assert len(xs) == 20
    assert len(w._cooldowns) == 20


# ──────────────────────────────────────────────────────────────────────────────
# Error response
# ──────────────────────────────────────────────────────────────────────────────


def test_error_response_shows_error_banner(app):
    """ok=False from engine must show error banner, not crash."""
    w = _make_widget()
    w._on_history_loaded({"ok": False, "error": "DB locked"})

    assert w._empty_label.isHidden()
    assert not w._error_label.isHidden()
    assert w._plot.isHidden()


def test_error_response_does_not_populate_scatter(app):
    """Error response must leave scatter empty."""
    w = _make_widget()
    w._on_history_loaded({"ok": False, "error": "timeout"})
    xs, ys = w._scatter.getData()
    assert xs is None or len(xs) == 0


# ──────────────────────────────────────────────────────────────────────────────
# ZMQ failure (no engine connection)
# ──────────────────────────────────────────────────────────────────────────────


def test_zmq_failure_graceful_empty(app):
    """If ZMQ returns ok=False (engine not running), widget stays in empty
    state without crashing — simulates 'construction without engine connection'
    acceptance criterion."""
    w = _make_widget()
    # Simulate ZMQ timeout/failure response
    w._on_history_loaded({"ok": False})
    assert not w._empty_label.isHidden() or not w._error_label.isHidden()
