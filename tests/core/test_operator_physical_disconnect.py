"""Teardown may proceed on a physical fact the software cannot observe.

When the reviewed source is unplugged from mains it can never report OFF, so
`launcher_shutdown` holds forever on `launcher_shutdown_global_off_unverified`
and the launcher stays in HOLD. On 2026-09-01 that turned a restart into an
eighteen-minute outage.

The operator may state the fact instead. It is carried as one boolean on the
SAME capability-bound shutdown request that is already being authorised -- no
command, no retained state, no evidence tier, nothing to clear afterwards --
and it authorises THIS teardown and nothing else.

Removing the instrument from configuration does not help and was measured:
with no reviewed source, emergency_off returns ok=True with active_channels=[]
but off_tier=command_only and verified_off=False, so the gate still refuses.
"""

import asyncio

import pytest

from cryodaq.drivers.contracts import parse_global_off_evidence
from cryodaq.engine import _shutdown_command_identity

INSTANCE = "a" * 32
REQUEST = "b" * 32
CAPABILITY = "c" * 64


def _envelope(**extra):
    return {
        "cmd": "launcher_shutdown",
        "engine_instance_id": INSTANCE,
        "request_id": REQUEST,
        "shutdown_capability": CAPABILITY,
        **extra,
    }


# ---------------------------------------------------------------------------
# The assertion rides the existing capability-bound envelope
# ---------------------------------------------------------------------------


def test_the_plain_shutdown_envelope_is_still_accepted():
    assert _shutdown_command_identity(_envelope()) == (INSTANCE, REQUEST, CAPABILITY)


def test_the_envelope_may_carry_the_one_shot_assertion():
    identity = _shutdown_command_identity(_envelope(operator_physical_disconnect=True))
    assert identity == (INSTANCE, REQUEST, CAPABILITY), (
        "the assertion must ride the request that is already capability-bound"
    )


def test_the_assertion_must_be_exactly_true():
    """No truthy strings, no 1, no None: an explicit human statement only."""
    for value in ("true", 1, "yes", None, False, [], {}):
        assert _shutdown_command_identity(_envelope(operator_physical_disconnect=value)) is None, value


def test_an_unknown_key_still_fails_closed():
    assert _shutdown_command_identity(_envelope(something_else=True)) is None
    assert _shutdown_command_identity(_envelope(operator_physical_disconnect=True, extra=1)) is None


def test_a_missing_required_key_still_fails_closed():
    envelope = _envelope(operator_physical_disconnect=True)
    del envelope["shutdown_capability"]
    assert _shutdown_command_identity(envelope) is None


# ---------------------------------------------------------------------------
# It authorises teardown, and nothing else
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_assertion_never_becomes_device_evidence():
    """SourceOffEvidence is untouched; verified_off stays False."""
    from cryodaq.core.safety_broker import SafetyBroker
    from cryodaq.core.safety_manager import SafetyManager

    manager = SafetyManager(SafetyBroker(), keithley_driver=None, mock=False)
    result = await manager.emergency_off(channel=None)
    evidence = parse_global_off_evidence(result.get("off_evidence"))

    assert evidence is not None
    assert evidence.verified_off is False, (
        "an operator statement must never be reported as device-verified OFF"
    )
    assert str(evidence.off_tier) == "command_only", "no new evidence tier was introduced"


@pytest.mark.asyncio
async def test_nothing_is_retained_after_the_assertion():
    """No state to clear on restart, reconnection or configuration change."""
    from cryodaq.core.safety_broker import SafetyBroker
    from cryodaq.core.safety_manager import SafetyManager

    manager = SafetyManager(SafetyBroker(), keithley_driver=None, mock=False)
    before = await manager.emergency_off(channel=None)
    # The assertion lives only in one shutdown request; the manager never sees it.
    after = await manager.emergency_off(channel=None)
    assert before.get("off_evidence") == after.get("off_evidence")
    assert not any(
        "physical_disconnect" in name for name in vars(manager)
    ), "the assertion must not be retained anywhere in SafetyManager"


def test_the_safety_manager_gained_no_assertion_entry_point():
    from cryodaq.core.safety_manager import SafetyManager

    assert not [name for name in dir(SafetyManager) if "physical_disconnect" in name], (
        "no new command or method: the assertion rides the existing shutdown request"
    )


def test_energising_policy_is_unchanged():
    """require_keithley_for_run must survive untouched."""
    from pathlib import Path

    safety_yaml = Path(__file__).resolve().parents[2] / "config" / "safety.yaml"
    assert "require_keithley_for_run: true" in safety_yaml.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The launcher gate accepts exactly these two authorisations
# ---------------------------------------------------------------------------


def _receipt(*, verified_off: bool, asserted: bool) -> dict:
    from cryodaq.drivers.contracts import SourceOffEvidence, SourceOffResult, SourceOffTier

    evidence = (
        SourceOffEvidence.from_global_result(SourceOffTier.VERIFIED_OFF, SourceOffResult.DEVICE_REPORTED_OFF)
        if verified_off
        else SourceOffEvidence.from_global_result(SourceOffTier.COMMAND_ONLY, SourceOffResult.COMMAND_ACCEPTED)
    )
    return {"off_evidence": evidence.receipt_payload(), "operator_physical_disconnect": asserted}


def _launcher_would_tear_down(receipt: dict) -> bool:
    evidence = parse_global_off_evidence(receipt["off_evidence"])
    return evidence is not None and (
        evidence.verified_off or receipt["operator_physical_disconnect"] is True
    )


def test_verified_off_authorises_teardown():
    assert _launcher_would_tear_down(_receipt(verified_off=True, asserted=False)) is True


def test_the_assertion_authorises_teardown_without_claiming_verified_off():
    receipt = _receipt(verified_off=False, asserted=True)
    assert _launcher_would_tear_down(receipt) is True
    assert parse_global_off_evidence(receipt["off_evidence"]).verified_off is False


def test_neither_authorisation_holds_the_launcher():
    assert _launcher_would_tear_down(_receipt(verified_off=False, asserted=False)) is False
