"""Safety contract tests for interlock authority and finite configuration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.interlock import (
    InterlockCondition,
    InterlockConfigError,
    InterlockEngine,
    InterlockState,
)
from cryodaq.drivers.base import ChannelStatus, Reading


def _condition(**overrides: object) -> InterlockCondition:
    values: dict[str, object] = {
        "name": "overheat",
        "description": "overheat",
        "channel_pattern": r"T1",
        "threshold": 300.0,
        "comparison": ">",
        "action": "emergency_off",
        "cooldown_s": 0.0,
    }
    values.update(overrides)
    return InterlockCondition(**values)  # type: ignore[arg-type]


def _reading() -> Reading:
    return Reading(
        channel="T1",
        value=350.0,
        unit="K",
        instrument_id="test",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        raw=350.0,
        metadata={},
    )


def test_engine_refuses_to_arm_without_safety_manager_authority() -> None:
    with pytest.raises(ValueError, match="trip_handler"):
        InterlockEngine(
            broker=DataBroker(),
            action_names={"emergency_off"},
        )


def test_direct_driver_callback_is_rejected_before_it_can_run() -> None:
    called: list[bool] = []

    async def direct_driver_callback() -> bool:
        called.append(True)
        return False

    async def authority_handler(condition: InterlockCondition, reading: Reading) -> bool:
        return True

    # The old actions mapping was an executable second authority. A mapping is
    # deliberately invalid now: only declarative action labels are accepted.
    with pytest.raises(TypeError, match="action_names"):
        InterlockEngine(
            DataBroker(),
            {"emergency_off": direct_driver_callback},
            trip_handler=authority_handler,
        )

    assert called == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [False, None])
async def test_unconfirmed_authority_result_never_logs_success(
    caplog: pytest.LogCaptureFixture, outcome: object
) -> None:
    async def authority_handler(condition: InterlockCondition, reading: Reading) -> object:
        return outcome

    engine = InterlockEngine(
        broker=DataBroker(),
        action_names={"emergency_off"},
        trip_handler=authority_handler,
    )
    engine.add_condition(_condition())

    with caplog.at_level(logging.CRITICAL, logger="cryodaq.core.interlock"):
        await engine._process_reading(_reading())

    assert engine.get_state()["overheat"] is InterlockState.TRIPPED
    assert "authority result was not confirmed" in caplog.text
    assert "authority action completed successfully" not in caplog.text


@pytest.mark.asyncio
async def test_authority_exception_is_visible_and_never_logs_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def authority_handler(condition: InterlockCondition, reading: Reading) -> bool:
        raise RuntimeError("OFF proof unavailable")

    engine = InterlockEngine(
        broker=DataBroker(),
        action_names={"emergency_off"},
        trip_handler=authority_handler,
    )
    engine.add_condition(_condition())

    with caplog.at_level(logging.CRITICAL, logger="cryodaq.core.interlock"):
        await engine._process_reading(_reading())

    assert engine.get_state()["overheat"] is InterlockState.TRIPPED
    assert "SafetyManager authority handler failed" in caplog.text
    assert "authority action completed successfully" not in caplog.text


@pytest.mark.parametrize("field", ["threshold", "cooldown_s"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_condition_rejects_nonfinite_values(field: str, value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        _condition(**{field: value})


def test_condition_accepts_finite_threshold_and_nonnegative_cooldown() -> None:
    condition = _condition(threshold=350.0, cooldown_s=1.0)
    assert condition.is_triggered(351.0)


@pytest.mark.parametrize("literal", [".nan", ".inf", "-.inf"])
@pytest.mark.parametrize("field", ["threshold", "cooldown_s"])
def test_yaml_rejects_nonfinite_interlock_values(tmp_path: Path, field: str, literal: str) -> None:
    config = tmp_path / "interlocks.yaml"
    config.write_text(
        "interlocks:\n"
        "  - name: invalid\n"
        "    description: invalid\n"
        "    channel_pattern: T1\n"
        "    threshold: 300\n"
        "    comparison: '>'\n"
        "    action: emergency_off\n"
        f"    {field}: {literal}\n",
        encoding="utf-8",
    )

    async def authority_handler(condition: InterlockCondition, reading: Reading) -> bool:
        return True

    engine = InterlockEngine(DataBroker(), action_names={"emergency_off"}, trip_handler=authority_handler)
    with pytest.raises(InterlockConfigError, match="finite"):
        engine.load_config(config)
    assert engine.get_state() == {}


def test_invalid_later_yaml_entry_does_not_partially_arm_configuration(tmp_path: Path) -> None:
    config = tmp_path / "interlocks.yaml"
    config.write_text(
        "interlocks:\n"
        "  - name: valid_but_must_not_arm\n"
        "    description: valid\n"
        "    channel_pattern: T1\n"
        "    threshold: 300\n"
        "    comparison: '>'\n"
        "    action: emergency_off\n"
        "  - name: invalid_later_entry\n"
        "    description: invalid\n"
        "    channel_pattern: T2\n"
        "    threshold: .nan\n"
        "    comparison: '>'\n"
        "    action: emergency_off\n",
        encoding="utf-8",
    )

    async def authority_handler(condition: InterlockCondition, reading: Reading) -> bool:
        return True

    engine = InterlockEngine(DataBroker(), action_names={"emergency_off"}, trip_handler=authority_handler)
    engine.add_condition(_condition(name="preexisting"))

    with pytest.raises(InterlockConfigError, match="finite"):
        engine.load_config(config)

    assert engine.get_state() == {"preexisting": InterlockState.ARMED}
