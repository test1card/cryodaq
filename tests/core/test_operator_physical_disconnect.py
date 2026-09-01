"""Teardown may proceed on a physical fact the software cannot observe.

When the reviewed source is unplugged from mains it can never report OFF, so
`launcher_shutdown` holds forever on `launcher_shutdown_global_off_unverified`
and the launcher stays in HOLD. On 2026-09-01 that turned a restart into an
eighteen-minute outage.

The operator may state the fact instead. It is carried as one boolean on the
SAME capability-bound shutdown request that is already being authorised -- no
command, no retained state, no evidence tier, no receipt field, no schema
change, nothing to clear afterwards -- and it authorises THIS teardown and
nothing else.

The receipt is deliberately unchanged. A SUCCESS receipt carrying unverified
evidence can only mean the engine accepted the assertion, because its gate
refuses otherwise; the receipt is already bound to engine instance and request
id; and the engine's CRITICAL log records the human reason. Echoing the flag
back would prove nothing the launcher does not already know.

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


def _receipt(*, verified_off: bool) -> dict:
    """The ORDINARY receipt shape. Unchanged by this work."""
    from cryodaq.drivers.contracts import SourceOffEvidence, SourceOffResult, SourceOffTier

    evidence = (
        SourceOffEvidence.from_global_result(SourceOffTier.VERIFIED_OFF, SourceOffResult.DEVICE_REPORTED_OFF)
        if verified_off
        else SourceOffEvidence.from_global_result(SourceOffTier.COMMAND_ONLY, SourceOffResult.COMMAND_ACCEPTED)
    )
    return {"off_evidence": evidence.receipt_payload()}


def _launcher_would_tear_down(receipt: dict, *, launcher_asserted: bool) -> bool:
    """The launcher's gate: device evidence, or its own asserted request."""
    evidence = parse_global_off_evidence(receipt["off_evidence"])
    return evidence is not None and (evidence.verified_off or launcher_asserted is True)


def test_verified_off_authorises_teardown():
    assert _launcher_would_tear_down(_receipt(verified_off=True), launcher_asserted=False) is True


def test_the_assertion_authorises_teardown_without_claiming_verified_off():
    receipt = _receipt(verified_off=False)
    assert _launcher_would_tear_down(receipt, launcher_asserted=True) is True
    assert parse_global_off_evidence(receipt["off_evidence"]).verified_off is False


def test_neither_authorisation_holds_the_launcher():
    assert _launcher_would_tear_down(_receipt(verified_off=False), launcher_asserted=False) is False


def test_the_ordinary_receipt_shape_is_unchanged():
    """No new mandatory field, so no schema bump and no ordinary-receipt churn.

    An ordinary shutdown must produce exactly the receipt it always did. The
    assertion changes what the launcher ACCEPTS, not what the engine reports.
    """
    from pathlib import Path

    from cryodaq import engine, launcher

    assert engine._ENGINE_SHUTDOWN_RECEIPT_SCHEMA == "cryodaq.engine_shutdown.v2"
    assert launcher._ENGINE_SHUTDOWN_RECEIPT_SCHEMA == "cryodaq.engine_shutdown.v2"

    source = (Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "launcher.py").read_text(encoding="utf-8")
    keys_block = source.split("expected_receipt_keys = {", 1)[1].split("}", 1)[0]
    assert "operator_physical_disconnect" not in keys_block, (
        "the assertion must not become a mandatory receipt field"
    )


def test_the_launcher_flag_dies_with_the_request_identity():
    """It can never outlive the request that carried it.

    Reset at every site that clears `_engine_shutdown_request_id`, and nowhere
    else, so a later teardown cannot inherit an earlier operator's statement.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "launcher.py").read_text(encoding="utf-8")
    request_resets = source.count("self._engine_shutdown_request_id = None")
    flag_resets = source.count("self._engine_shutdown_operator_asserted = False")
    assert request_resets > 0
    assert flag_resets == request_resets, (
        f"{flag_resets} flag resets for {request_resets} request-identity resets"
    )


# ---------------------------------------------------------------------------
# The standing declaration: read from the profile, never inferred
# ---------------------------------------------------------------------------


def _profile(tmp_path, entry_extra: dict) -> None:
    import yaml

    (tmp_path / "instruments.local.yaml").write_text(
        yaml.safe_dump(
            {"instruments": [{"type": "keithley_2604b", "name": "Keithley_1", **entry_extra}]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


@pytest.fixture
def profile_dir(tmp_path, monkeypatch):
    import cryodaq.paths

    monkeypatch.setattr(cryodaq.paths, "get_config_dir", lambda: tmp_path)
    return tmp_path


def test_a_complete_declaration_is_honoured(profile_dir):
    from cryodaq.launcher import _reviewed_source_declared_physically_disconnected

    _profile(profile_dir, {
        "physically_disconnected": True,
        "physically_disconnected_note": "2026-08-31 unplugged by V.F.",
    })
    assert _reviewed_source_declared_physically_disconnected() is True


def test_a_declaration_without_a_note_is_ignored(profile_dir):
    """A statement that cannot say who made it or when is a leftover."""
    from cryodaq.launcher import _reviewed_source_declared_physically_disconnected

    _profile(profile_dir, {"physically_disconnected": True})
    assert _reviewed_source_declared_physically_disconnected() is False


def test_an_empty_note_is_ignored(profile_dir):
    from cryodaq.launcher import _reviewed_source_declared_physically_disconnected

    _profile(profile_dir, {"physically_disconnected": True, "physically_disconnected_note": "   "})
    assert _reviewed_source_declared_physically_disconnected() is False


def test_no_declaration_means_not_declared(profile_dir):
    from cryodaq.launcher import _reviewed_source_declared_physically_disconnected

    _profile(profile_dir, {})
    assert _reviewed_source_declared_physically_disconnected() is False


def test_a_missing_profile_fails_closed(profile_dir):
    from cryodaq.launcher import _reviewed_source_declared_physically_disconnected

    assert _reviewed_source_declared_physically_disconnected() is False


def test_an_unreadable_profile_fails_closed(profile_dir):
    from cryodaq.launcher import _reviewed_source_declared_physically_disconnected

    (profile_dir / "instruments.local.yaml").write_text("{[not yaml", encoding="utf-8")
    assert _reviewed_source_declared_physically_disconnected() is False


# ---------------------------------------------------------------------------
# Teardown is released, and nothing else is
# ---------------------------------------------------------------------------


def _teardown_released(*, verified_off: bool, declared: bool) -> bool:
    """Drive the real release gate, not a copy of its condition."""
    from types import SimpleNamespace

    from cryodaq.drivers.contracts import SourceOffEvidence, SourceOffResult, SourceOffTier
    from cryodaq.engine import PROTOCOL_VERSION, _request_teardown_after_shutdown_receipt

    evidence = (
        SourceOffEvidence.from_global_result(SourceOffTier.VERIFIED_OFF, SourceOffResult.DEVICE_REPORTED_OFF)
        if verified_off
        else SourceOffEvidence.from_global_result(SourceOffTier.COMMAND_ONLY, SourceOffResult.COMMAND_ACCEPTED)
    )
    receipt = {
        "ok": True,
        "engine_instance_id": INSTANCE,
        "request_id": REQUEST,
        "off_evidence": evidence.receipt_payload(),
        "teardown_requested": True,
    }
    released: list[bool] = []
    context = SimpleNamespace(
        shutdown_receipt=receipt,
        engine_instance_id=INSTANCE,
        shutdown_event=SimpleNamespace(set=lambda: released.append(True)),
    )
    cmd = _envelope(**({"operator_physical_disconnect": True} if declared else {}))
    _request_teardown_after_shutdown_receipt(context, cmd, {**receipt, "proto": PROTOCOL_VERSION})
    return bool(released)


def test_verified_off_releases_teardown():
    assert _teardown_released(verified_off=True, declared=False) is True


def test_the_declaration_releases_teardown_without_device_evidence():
    """The gap that made the committed assertion inert."""
    assert _teardown_released(verified_off=False, declared=True) is True


def test_neither_leaves_the_engine_running():
    assert _teardown_released(verified_off=False, declared=False) is False
