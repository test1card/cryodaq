"""Tests for shift handover modal re-entrancy and auto-dismiss."""
from __future__ import annotations

import inspect


def test_periodic_prompt_reentrant_guard():
    """Second _on_periodic_due must be skipped if dialog already open."""
    from cryodaq.gui.widgets.shift_handover import ShiftBar
    source = inspect.getsource(ShiftBar._on_periodic_due)
    # Guard pattern: check _prompt_pending → return, THEN set _prompt_pending = True
    check_idx = source.find("if self._prompt_pending")
    set_idx = source.find("self._prompt_pending = True")
    assert check_idx != -1, "_on_periodic_due must check _prompt_pending"
    assert set_idx != -1, "_on_periodic_due must set _prompt_pending"
    assert check_idx < set_idx, "Guard must come BEFORE setting _prompt_pending"


def test_periodic_missed_auto_dismisses_dialog():
    """_on_periodic_missed must call reject() on open dialog."""
    from cryodaq.gui.widgets.shift_handover import ShiftBar
    source = inspect.getsource(ShiftBar._on_periodic_missed)
    assert "reject()" in source, "_on_periodic_missed must auto-dismiss dialog via reject()"
    assert "_prompt_dialog" in source, "_on_periodic_missed must reference _prompt_dialog"
