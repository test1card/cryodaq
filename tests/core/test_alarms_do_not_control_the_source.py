"""Alarms observe and notify. Only SafetyManager changes source state.

The boundary, as agreed in review on 2026-09-03:

* **Advisory** — cooldown trajectory, vacuum guard, stationarity, sensor
  diagnostics. These raise alarms and notifications. They do not de-energise.
* **Authoritative** — hard source limits, interlocks, source faults,
  persistence and safety shutdowns, emergency stop. Each keeps its own
  independent de-energisation path, and muting notifications does not disarm
  any of them.

Two things forced this. The vacuum guard latched the Keithley on the first
cooldown it ever saw, on a threshold every recorded cooldown on this stand would
have exceeded. And `CooldownAlarm` held a SafetyManager handle unconditionally,
so a trajectory deviation — precisely what a cooldown from a poor vacuum
produces — would have done the same, with no way to opt out.

A config gate was tried and was not real: the accepted cooldown schema rejects
unknown keys, so `escalate_to_safety` could not be set without invalidating the
whole configuration, and its absence left the gate permanently closed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_ENGINE = Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "engine.py"
_ADVISORY_ALARMS = ("CooldownAlarm", "VacuumGuard")


def _keyword_source(call: ast.Call, name: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return ast.unparse(keyword.value)
    return None


def _construction_calls(class_name: str) -> list[ast.Call]:
    tree = ast.parse(_ENGINE.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == class_name
    ]


@pytest.mark.parametrize("alarm", _ADVISORY_ALARMS)
def test_no_advisory_alarm_is_given_a_safety_manager(alarm: str) -> None:
    """The handle must not be passed at all — not merely gated off.

    Asserting on the construction site rather than on runtime behaviour is
    deliberate: it catches the wiring being restored, which is how this arrived
    both times.
    """

    calls = _construction_calls(alarm)
    assert calls, f"{alarm} is not constructed in engine.py — has it moved?"
    for call in calls:
        passed = _keyword_source(call, "safety_manager")
        assert passed in (None, "None"), (
            f"{alarm} is wired with safety_manager={passed!r}; an advisory alarm "
            "must not hold authority over the source"
        )


def test_the_over_temperature_interlocks_are_untouched() -> None:
    """Hard protection keeps its independent path.

    Muting or demoting alarms must never disarm the interlocks; they are the
    reason a stuck heater does not cook the stage.
    """

    import yaml

    config = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "config" / "interlocks.yaml").read_text(encoding="utf-8")
    )
    actions = {entry["name"]: entry["action"] for entry in config["interlocks"]}
    assert actions.get("overheat_cryostat") == "emergency_off"
    assert actions.get("source_overtemp") == "stop_source"


def test_the_cooldown_schema_still_rejects_the_dead_knob() -> None:
    """`cooldown.escalate_to_safety` was never an accepted key.

    Recorded so the next person does not add it back believing it does
    something: the schema requires an exact key set, so a configuration
    carrying it fails to load entirely.
    """

    from cryodaq.core.physical_alarms_config import _COOLDOWN_DEFAULTS

    assert "escalate_to_safety" not in _COOLDOWN_DEFAULTS
