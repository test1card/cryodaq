"""A3b — BottomStatusBar repeating fault-latched beep.

``_fault_beep_active`` is covered without Qt directly (pure). The rest
covers the QTimer start/stop wiring on a real (offscreen) widget.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.bottom_status_bar import BottomStatusBar, _fault_beep_active


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Part (a): pure _fault_beep_active
# ---------------------------------------------------------------------------


def test_fault_latched_is_active() -> None:
    assert _fault_beep_active("fault_latched") is True


def test_fault_latched_is_case_insensitive() -> None:
    assert _fault_beep_active("FAULT_LATCHED") is True


def test_none_is_not_active() -> None:
    assert _fault_beep_active(None) is False


def test_other_states_are_not_active() -> None:
    for state in ("safe_off", "ready", "run_permitted", "running", "manual_recovery"):
        assert _fault_beep_active(state) is False, state


# ---------------------------------------------------------------------------
# Part (b): widget wiring
# ---------------------------------------------------------------------------


def _make_bar() -> BottomStatusBar:
    _app()
    bar = BottomStatusBar()
    bar._timer.stop()
    return bar


def test_fault_latched_starts_the_repeating_beep_timer() -> None:
    bar = _make_bar()
    assert not bar._fault_beep_timer.isActive()
    bar.set_safety_state("fault_latched")
    assert bar._fault_beep_timer.isActive()


def test_leaving_fault_latched_stops_the_timer() -> None:
    bar = _make_bar()
    bar.set_safety_state("fault_latched")
    assert bar._fault_beep_timer.isActive()
    bar.set_safety_state("ready")
    assert not bar._fault_beep_timer.isActive()


def test_blanking_state_on_connection_loss_stops_the_timer() -> None:
    bar = _make_bar()
    bar.set_safety_state("fault_latched")
    assert bar._fault_beep_timer.isActive()
    bar.set_safety_state(None)
    assert not bar._fault_beep_timer.isActive()


def test_repeated_fault_latched_calls_do_not_restart_a_running_timer() -> None:
    """Idempotent: set_safety_state may be called every poll tick while
    latched — must not keep re-triggering the immediate beep."""
    bar = _make_bar()
    bar.set_safety_state("fault_latched")
    timer_id_before = id(bar._fault_beep_timer)
    bar.set_safety_state("fault_latched")
    assert bar._fault_beep_timer.isActive()
    assert id(bar._fault_beep_timer) == timer_id_before


def test_non_fault_state_never_starts_the_timer() -> None:
    bar = _make_bar()
    bar.set_safety_state("running")
    assert not bar._fault_beep_timer.isActive()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
