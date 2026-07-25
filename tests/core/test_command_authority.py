from __future__ import annotations

import pytest

from cryodaq.core.command_authority import (
    SafeDirectionKind,
    exact_safe_direction_kind,
    is_preemptive_safe_direction,
)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            {"cmd": "keithley_emergency_off", "channel": "smua"},
            SafeDirectionKind.TARGETED_OFF,
        ),
        (
            {"cmd": "keithley_emergency_off", "channel": "smub"},
            SafeDirectionKind.TARGETED_OFF,
        ),
        (
            {"cmd": "keithley_emergency_off"},
            SafeDirectionKind.GLOBAL_OFF,
        ),
        (
            {
                "cmd": "launcher_shutdown",
                "engine_instance_id": "a" * 32,
                "request_id": "b" * 32,
                "shutdown_capability": "c" * 64,
            },
            SafeDirectionKind.LAUNCHER_SHUTDOWN,
        ),
    ],
)
def test_exact_safe_direction_kind_accepts_only_canonical_envelopes(
    command: dict[str, str],
    expected: SafeDirectionKind,
) -> None:
    assert exact_safe_direction_kind(command) is expected
    assert is_preemptive_safe_direction(command) is True


class _DictSubclass(dict):
    pass


@pytest.mark.parametrize(
    "command",
    [
        None,
        [],
        _DictSubclass(cmd="keithley_emergency_off"),
        {},
        {"cmd": "keithley_emergency_off", "channel": ""},
        {"cmd": "keithley_emergency_off", "channel": "SMUA"},
        {"cmd": "keithley_emergency_off", "channel": None},
        {"cmd": "keithley_emergency_off", "channel": "smua", "extra": True},
        {"cmd": "launcher_shutdown"},
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "A" * 32,
            "request_id": "b" * 32,
            "shutdown_capability": "c" * 64,
        },
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 31,
            "request_id": "b" * 32,
            "shutdown_capability": "c" * 64,
        },
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "b" * 33,
            "shutdown_capability": "c" * 64,
        },
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "b" * 32,
            "shutdown_capability": "c" * 63,
        },
        {
            "cmd": "launcher_shutdown",
            "engine_instance_id": "a" * 32,
            "request_id": "b" * 32,
            "shutdown_capability": "c" * 64,
            "extra": "authority widening",
        },
    ],
)
def test_safe_direction_classifier_rejects_every_noncanonical_shape(command: object) -> None:
    assert exact_safe_direction_kind(command) is None
    assert is_preemptive_safe_direction(command) is False
