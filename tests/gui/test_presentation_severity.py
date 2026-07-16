from __future__ import annotations

import pytest

from cryodaq.gui.presentation_severity import alarm_level_for_display, operator_state_for_display
from cryodaq.operator_snapshot import OperatorPresentationState


def test_warning_aliases_caution_only_at_operator_presentation_boundary() -> None:
    assert operator_state_for_display(OperatorPresentationState.WARNING) is OperatorPresentationState.CAUTION
    assert operator_state_for_display(OperatorPresentationState.FAULT) is OperatorPresentationState.FAULT
    assert alarm_level_for_display("WARNING") == "CAUTION"
    assert alarm_level_for_display("caution") == "CAUTION"
    assert alarm_level_for_display("CRITICAL") == "CRITICAL"


def test_unknown_alarm_level_is_conspicuous_not_caution() -> None:
    assert alarm_level_for_display("") == "UNKNOWN"
    assert alarm_level_for_display("future-level") == "UNKNOWN"
    with pytest.raises(TypeError):
        alarm_level_for_display(None)  # type: ignore[arg-type]
