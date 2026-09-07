"""A calibration start must not be refused forever.

`_unresolved_start_name` was cleared only when a fresh status carried an
`experiment_name` equal to the name just started. `CalibrationAcquisitionService.stats`
returns active, point_count, t_min, t_max, reference_channel and
target_channels — it has never carried `experiment_name`. So the comparison was
always "" == <name>, the flag never cleared, and every calibration start after
the first was refused with "исход предыдущего запуска ещё не подтверждён" until
someone restarted the GUI.

CryoDAQ informs; the operator decides. A veto waiting on a confirmation that
cannot arrive is not a safety feature.

The handler is exercised against a stand-in `self` rather than a constructed
panel: the defect is in this function's logic, and building the real widget
offscreen crashes the interpreter.
"""

from __future__ import annotations

from typing import Any

from cryodaq.core.calibration_acquisition import CalibrationAcquisitionService
from cryodaq.gui.shell.overlays.calibration_panel import CalibrationPanel


class _Panel:
    """Only what `_on_mode_result` actually touches."""

    def __init__(self, *, mode: str = "acquisition") -> None:
        self._mode_worker = None
        self._connection_generation = 1
        self._connected = True
        self._current_mode = mode
        self._unresolved_apply = None
        self._unresolved_start_name = ""
        self.messages: list[tuple[str, str]] = []
        self._acquisition_widget = _Widget()
        self._results_widget = _Widget()

    def show_info(self, text: str, **_kw: Any) -> None:
        self.messages.append(("info", text))

    def show_warning(self, text: str, **_kw: Any) -> None:
        self.messages.append(("warning", text))

    def show_error(self, text: str, **_kw: Any) -> None:
        self.messages.append(("error", text))

    def _switch_mode(self, mode: str) -> None:
        self._current_mode = mode


class _Widget:
    def update_stats(self, _result: Any) -> None: ...
    def update_coverage(self, _bins: Any) -> None: ...
    def set_channels(self, _channels: Any) -> None: ...


def _deliver(panel: _Panel, result: dict) -> None:
    CalibrationPanel._on_mode_result(panel, result, worker=None, generation=None)


def test_the_engine_status_really_does_not_carry_the_field_it_was_gated_on() -> None:
    """The premise of the bug, asserted so it cannot quietly come back."""
    keys = set(CalibrationAcquisitionService(writer=None).stats)
    assert "experiment_name" not in keys, "the field is back; the panel's confirmation may key on it again"
    assert "active" in keys, "the panel confirms a start by the run being active"


def test_coverage_bins_still_has_no_producer() -> None:
    """The branch reading it no-ops. Recorded so a reader is not misled."""
    assert "coverage_bins" not in set(CalibrationAcquisitionService(writer=None).stats)


def test_an_active_status_confirms_the_start() -> None:
    panel = _Panel()
    panel._unresolved_start_name = "Cooldown-001"

    _deliver(panel, {"ok": True, "active": True})

    assert panel._unresolved_start_name == "", "the start was never confirmed"
    assert any(kind == "info" for kind, _ in panel.messages)


def test_an_inactive_status_releases_the_operator_rather_than_holding_the_panel() -> None:
    """The start did not take. That is news, not a reason to lock the panel."""
    panel = _Panel(mode="setup")
    panel._unresolved_start_name = "Cooldown-001"

    _deliver(panel, {"ok": True, "active": False})

    assert panel._unresolved_start_name == ""
    assert panel.messages, "the operator was told nothing about their start"


def test_a_second_start_is_possible_after_a_first_one_completed() -> None:
    """The regression itself, end to end."""
    panel = _Panel()
    panel._unresolved_start_name = "Cooldown-001"

    _deliver(panel, {"ok": True, "active": True})
    _deliver(panel, {"ok": True, "active": False, "target_channels": ["Т1"]})

    assert panel._unresolved_start_name == "", "the panel is latched: no further calibration can ever be started"


def test_a_deactivating_run_still_moves_to_results() -> None:
    """Releasing the operator must not cost the existing mode transition."""
    panel = _Panel(mode="acquisition")

    _deliver(panel, {"ok": True, "active": False, "target_channels": ["Т1", "Т2"]})

    assert panel._current_mode == "results"


def test_a_failed_status_does_not_clear_the_flag() -> None:
    """`ok: False` is not news about the run; it is a failure to ask."""
    panel = _Panel()
    panel._unresolved_start_name = "Cooldown-001"

    _deliver(panel, {"ok": False})

    assert panel._unresolved_start_name == "Cooldown-001"
