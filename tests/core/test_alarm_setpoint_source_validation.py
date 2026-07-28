"""Load-time rejection of an undefined `setpoint_source`.

An unknown `setpoint_source` key used to resolve to a determined `0.0`, so a
mistyped reference produced an alarm that silently compared against zero kelvin.
Config load now rejects it, naming both the alarm and the offending key.

This lives in its own file rather than in ``test_alarm_config_validation.py``
deliberately. That file's exact blob is pinned by the immutable red-reproduction
receipt for ``ALARM-PHASE-ELAPSED-SUBCONDITION-026``
(``governance/red_reproductions/alarm_phase_elapsed_subcondition_026.json``).
Appending a test there changes its blob, the governance contract rejects the
mismatch, and every sealed CI partition fails before pytest runs. Add
setpoint-validation tests here, not there.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cryodaq.core.alarm_config import AlarmConfigError, load_alarm_config


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "alarms_v3.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def test_deviation_from_setpoint_unknown_setpoint_source_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        engine:
          setpoints:
            T12_setpoint:
              source: experiment_metadata
              default: 4.2
        global_alarms:
          drift:
            alarm_type: threshold
            channel: T12
            check: deviation_from_setpoint
            setpoint_source: T12_setpoint_typo
            threshold: 0.5
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError) as exc_info:
        load_alarm_config(p)
    assert str(exc_info.value) == (
        "alarm 'drift' (check=deviation_from_setpoint) has undefined setpoint_source 'T12_setpoint_typo'"
    )
