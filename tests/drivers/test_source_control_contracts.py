from __future__ import annotations

import inspect
from dataclasses import fields, is_dataclass

import cryodaq.drivers.contracts as contracts


def test_source_control_value_shapes_are_exact() -> None:
    source_off_tier = getattr(contracts, "SourceOffTier")
    source_adjustment_mode = getattr(contracts, "SourceAdjustmentMode")
    source_setpoint = getattr(contracts, "SourceSetpoint")
    source_descriptor = getattr(contracts, "SourceDescriptor")

    assert {member.name: member.value for member in source_off_tier} == {
        "COMMAND_ONLY": "command_only",
        "VERIFIED_OFF": "verified_off",
    }
    assert {member.name: member.value for member in source_adjustment_mode} == {
        "START_STOP_ONLY": "start_stop_only",
        "LIVE_UPDATE": "live_update",
    }
    for value_type, field_names in (
        (source_setpoint, ("p_target", "v_compliance", "i_compliance")),
        (source_descriptor, ("off_tier", "adjustment_mode")),
    ):
        assert is_dataclass(value_type)
        assert value_type.__dataclass_params__.frozen
        assert value_type.__slots__ == field_names
        assert tuple(field.name for field in fields(value_type)) == field_names


def test_adjustable_controlled_source_declares_exact_additional_surface() -> None:
    adjustable_controlled_source = getattr(contracts, "AdjustableControlledSource")

    assert contracts.declared_protocol_members(adjustable_controlled_source) == (
        "source_connection_generation",
        "source_setpoints",
        "update_source_limits",
        "update_source_target",
    )
    assert tuple(inspect.signature(adjustable_controlled_source.update_source_target).parameters) == (
        "self",
        "channel",
        "p_target",
    )
    assert tuple(inspect.signature(adjustable_controlled_source.update_source_limits).parameters) == (
        "self",
        "channel",
        "v_compliance",
        "i_compliance",
    )


def test_legacy_controlled_source_surface_remains_unchanged() -> None:
    assert contracts.declared_protocol_members(contracts.ControlledSource) == (
        "start_source",
        "stop_source",
    )


def test_descriptor_discloses_command_only_lower_tier() -> None:
    describe_controlled_source = getattr(contracts, "describe_controlled_source")
    source_off_tier = getattr(contracts, "SourceOffTier")
    source_adjustment_mode = getattr(contracts, "SourceAdjustmentMode")

    class CommandOnlySource:
        async def start_source(
            self,
            channel: str,
            p_target: float,
            v_compliance: float,
            i_compliance: float,
        ) -> None: ...

        async def stop_source(self, channel: str) -> None: ...

    descriptor = describe_controlled_source(CommandOnlySource())
    assert descriptor.off_tier is source_off_tier.COMMAND_ONLY
    assert descriptor.adjustment_mode is source_adjustment_mode.START_STOP_ONLY


def test_descriptor_preserves_verified_legacy_source_without_promoting_adjustability() -> None:
    describe_controlled_source = getattr(contracts, "describe_controlled_source")
    source_off_tier = getattr(contracts, "SourceOffTier")
    source_adjustment_mode = getattr(contracts, "SourceAdjustmentMode")

    class VerifiedLegacySource:
        async def start_source(
            self,
            channel: str,
            p_target: float,
            v_compliance: float,
            i_compliance: float,
        ) -> None: ...

        async def stop_source(self, channel: str) -> None: ...

        async def emergency_off(self, channel: str | None = None) -> bool:
            return True

        @property
        def output_state_unverified(self) -> bool:
            return False

    descriptor = describe_controlled_source(VerifiedLegacySource())
    assert descriptor.off_tier is source_off_tier.VERIFIED_OFF
    assert descriptor.adjustment_mode is source_adjustment_mode.START_STOP_ONLY


def test_descriptor_classifies_full_adjustable_verified_source() -> None:
    describe_controlled_source = getattr(contracts, "describe_controlled_source")
    source_off_tier = getattr(contracts, "SourceOffTier")
    source_adjustment_mode = getattr(contracts, "SourceAdjustmentMode")
    source_setpoint = getattr(contracts, "SourceSetpoint")

    class AdjustableVerifiedSource:
        async def start_source(
            self,
            channel: str,
            p_target: float,
            v_compliance: float,
            i_compliance: float,
        ) -> None: ...

        async def stop_source(self, channel: str) -> None: ...

        async def emergency_off(self, channel: str | None = None) -> bool:
            return True

        @property
        def output_state_unverified(self) -> bool:
            return False

        @property
        def source_connection_generation(self) -> int:
            return 1

        @property
        def source_setpoints(self) -> dict[str, object]:
            return {"ch1": source_setpoint(1.0, 2.0, 3.0)}

        async def update_source_target(self, channel: str, p_target: float) -> None: ...

        async def update_source_limits(
            self,
            channel: str,
            *,
            v_compliance: float | None = None,
            i_compliance: float | None = None,
        ) -> None: ...

    descriptor = describe_controlled_source(AdjustableVerifiedSource())
    assert descriptor.off_tier is source_off_tier.VERIFIED_OFF
    assert descriptor.adjustment_mode is source_adjustment_mode.LIVE_UPDATE
